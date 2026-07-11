"""Chat API — ``POST /api/chat`` (SSE stream) + ``POST /api/chat/{session}/cancel`` (§9).

This router is deliberately **thin** (Router → Service → Agent/Repository): it
validates the request, gets a :class:`~app.services.chat.ChatService`, and adapts
the service's typed :class:`~app.schemas.chat.ChatEvent` stream to the Server-Sent
Events wire format. All the model ⇄ tools loop logic lives in the service — no
business logic here. The cancel endpoint likewise just delegates to
:meth:`~app.services.chat.ChatService.request_cancel` (which sets a Redis-backed flag
the in-flight stream polls — replacing v1's in-process ``active_requests`` dict, §4).

SSE framing: each event is emitted as ``event: <name>\\ndata: <json>\\n\\n`` where
``<name>`` is the event's ``event`` field and ``<json>`` is its remaining fields.
The ``text/event-stream`` content type also opts the response out of gzip
(Starlette excludes it), so tokens are not buffered by compression.

Dependency wiring is intentionally lazy: the :class:`ChatService` is assembled by the
composition root (:func:`app.bootstrap.build_chat_service`) on first use and cached on
``app.state``. This router imports **no** repository/LLM types — it only holds the
:func:`get_chat_service` dependency and the SSE plumbing, keeping the layering
(Router → Service → Agent/Repository) clean. Tests override :func:`get_chat_service` to
inject a fake, so the real router / Redis / HF wiring never runs in unit tests.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import StreamingResponse

from app.app_state import AppStateKeys
from app.bootstrap import build_chat_service
from app.schemas.auth import CurrentUser
from app.schemas.chat import ChatEvent, ChatRequest
from app.security.dependencies import (
    authorize_session_access,
    get_rate_limit_service,
    rate_limit_exceeded_http,
    require_auth,
)
from app.services.chat import ChatService
from app.services.rate_limiting import RateLimitAction, RateLimitExceeded, RateLimitService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def get_chat_service(request: Request) -> ChatService:
    """FastAPI dependency: the app-scoped :class:`ChatService`, built once and cached.

    Delegates construction to the composition root (:func:`app.bootstrap.build_chat_service`)
    and caches the singleton on ``app.state``. Tests override this dependency to inject a
    fake service, so the real router / Redis / HF wiring never runs in unit tests.
    """
    service: ChatService | None = getattr(request.app.state, AppStateKeys.CHAT_SERVICE, None)
    if service is None:
        service = build_chat_service(request.app)
        setattr(request.app.state, AppStateKeys.CHAT_SERVICE, service)
    return service


def _format_sse(event: ChatEvent) -> str:
    """Render one :class:`ChatEvent` as an SSE frame."""
    data = event.model_dump(exclude={"event"})
    return f"event: {event.event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    current_user: CurrentUser = Depends(require_auth),
    service: ChatService = Depends(get_chat_service),
    rate_limiter: RateLimitService = Depends(get_rate_limit_service),
) -> StreamingResponse:
    """Stream a chat turn as Server-Sent Events (authenticated, own-session, rate-limited).

    Requires a valid bearer token (guest or user). Before any streaming begins the router
    (1) enforces **own-data-only** access — the request's ``session_id`` must be the caller's
    own session (else ``403``) — and (2) applies the Redis-backed **rate limit** for the
    caller's tier (guest: 10 messages/session; user: generous per-window), returning ``429``
    with an upgrade prompt when over budget. The turn's ``user_id`` is taken from the verified
    token, never from the request body (§7 AuthZ), so a client cannot act as another user.

    The response is a live ``text/event-stream``: ``start`` → ``token`` / ``tool_call`` /
    ``tool_result`` (repeated as the model works) → ``done`` on success, or a single terminal
    ``error`` event. The service never raises into the response body, so the stream always
    ends cleanly (no mid-stream 500).
    """
    # Own-data-only first (a rejected cross-session request must not consume the rate budget),
    # then count this message against the caller's tier before opening the stream.
    authorize_session_access(payload.session_id, current_user)
    try:
        await rate_limiter.enforce(RateLimitAction.MESSAGE, current_user)
    except RateLimitExceeded as exc:
        raise rate_limit_exceeded_http(exc) from exc

    async def event_stream() -> AsyncIterator[str]:
        async for event in service.stream_turn(
            payload.session_id,
            payload.message,
            history=payload.history,
            user_id=current_user.user_id,
        ):
            yield _format_sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Disable proxy (e.g. nginx) response buffering so tokens flush live.
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/{session}/cancel", status_code=202)
async def cancel_chat(
    session: str = Path(..., min_length=1, max_length=200),
    current_user: CurrentUser = Depends(require_auth),
    service: ChatService = Depends(get_chat_service),
) -> dict[str, str]:
    """Request cancellation of the in-flight chat turn for ``session`` (design §9).

    Requires a valid bearer token and enforces **own-data-only** access: a caller may only
    cancel *their own* session (else ``403``) — closing the P1 gap where anyone who knew a
    ``session_id`` could cancel it. Sets a Redis-backed cancel flag and returns **promptly**
    — it does not block waiting for the stream to stop. The in-flight ``POST /api/chat`` turn
    for the same ``session_id`` observes the flag at its next checkpoint and ends its SSE
    stream with a terminal ``cancelled`` event. Idempotent: cancelling an idle session is a
    no-op that still returns 202 (the flag self-expires via TTL).
    """
    authorize_session_access(session, current_user)
    await service.request_cancel(session)
    return {"status": "cancelling", "session": session}
