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

Dependency wiring is intentionally lazy for P1: the :class:`ChatService` (and the
:class:`~app.llm.router.LLMRouter` + Redis session memory / circuit-breaker it needs)
is built on first use and cached on ``app.state``. The shared ``redis.asyncio`` pool
now comes from :class:`~app.repositories.redis.RedisConnectionProvider` (§4) — both the
session memory and the router's circuit-breaker acquire the *same* client from it; P2
moves the rest of the composition to shared pools. Tests override
:func:`get_chat_service` to inject a fake.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import cast

from fastapi import APIRouter, Depends, FastAPI, Path, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.repositories.redis import (
    CancelRedis,
    RedisCancelRegistry,
    RedisConnectionProvider,
    RedisSessionMemory,
    SessionRedis,
)
from app.schemas.chat import ChatEvent, ChatRequest
from app.services.chat import ChatService
from app.tools.registry import build_default_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

#: Attribute on ``app.state`` caching the lazily-built singleton service.
_SERVICE_ATTR = "chat_service"
#: Attribute on ``app.state`` caching the shared Redis pool provider (closed on shutdown).
_REDIS_PROVIDER_ATTR = "redis_provider"


def build_chat_service(app: FastAPI) -> ChatService:
    """Construct the default :class:`ChatService` from application settings.

    The shared ``redis.asyncio`` connection pool (§4) is owned by a
    :class:`~app.repositories.redis.RedisConnectionProvider` stashed on ``app.state``
    so the lifespan can close it on shutdown. The **one** client from that pool is
    shared by the router's circuit-breaker, the Redis-backed session memory, and the
    Redis-backed cancel registry — no per-request/per-feature ``Redis()`` clients. The
    tool registry is the P1-03 default. (P2 moves the remaining composition to shared
    pools.)
    """
    from app.llm.router import LLMRouter, RedisLike

    provider = RedisConnectionProvider.from_settings(settings)
    app.state.redis_provider = provider
    redis_client = provider.client()

    # The one shared client implements the router's ``RedisLike`` seam, the session
    # memory's ``SessionRedis`` seam, and the cancel registry's ``CancelRedis`` seam.
    # redis-py's own method signatures are too loose (``Awaitable[Any] | Any`` returns)
    # to structurally satisfy those strict Protocols under mypy, so cast at this single
    # composition-root boundary.
    llm_router = LLMRouter.from_settings(settings, redis_client=cast("RedisLike", redis_client))
    registry = build_default_registry(settings)
    memory = RedisSessionMemory.from_settings(cast(SessionRedis, redis_client), settings)
    cancel = RedisCancelRegistry.from_settings(cast(CancelRedis, redis_client), settings)
    return ChatService(llm_router, registry, memory, cancel)


def get_chat_service(request: Request) -> ChatService:
    """FastAPI dependency: the app-scoped :class:`ChatService`, built once and cached.

    Tests override this dependency to inject a fake service, so the real router /
    Redis / HF wiring never runs in unit tests.
    """
    service: ChatService | None = getattr(request.app.state, _SERVICE_ATTR, None)
    if service is None:
        service = build_chat_service(request.app)
        setattr(request.app.state, _SERVICE_ATTR, service)
    return service


def _format_sse(event: ChatEvent) -> str:
    """Render one :class:`ChatEvent` as an SSE frame."""
    data = event.model_dump(exclude={"event"})
    return f"event: {event.event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    """Stream a chat turn as Server-Sent Events.

    The response is a live ``text/event-stream``: ``start`` → ``token`` /
    ``tool_call`` / ``tool_result`` (repeated as the model works) → ``done`` on
    success, or a single terminal ``error`` event. The service never raises into the
    response body, so the stream always ends cleanly (no mid-stream 500).
    """

    async def event_stream() -> AsyncIterator[str]:
        async for event in service.stream_turn(
            payload.session_id, payload.message, history=payload.history
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
    service: ChatService = Depends(get_chat_service),
) -> dict[str, str]:
    """Request cancellation of the in-flight chat turn for ``session`` (design §9).

    Sets a Redis-backed cancel flag and returns **promptly** — it does not block
    waiting for the stream to stop. The in-flight ``POST /api/chat`` turn for the same
    ``session_id`` observes the flag at its next checkpoint and ends its SSE stream with
    a terminal ``cancelled`` event. Idempotent: cancelling an idle session is a no-op
    that still returns 202 (the flag self-expires via TTL).

    .. note::
       No auth/ownership check yet — anyone who knows a ``session_id`` can cancel it.
       Per-session/user access control + rate limits land with the P3 AuthZ task.
    """
    await service.request_cancel(session)
    return {"status": "cancelling", "session": session}
