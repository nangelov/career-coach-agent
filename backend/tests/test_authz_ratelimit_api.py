"""API-level tests for P3-04 AuthZ (own-data-only) + Redis rate limits on ``POST /api/chat``.

Drives the real chat router with a fake chat service (canned SSE), a stand-in authenticated
caller (``require_auth`` override), and a real :class:`~app.services.rate_limiting.RateLimitService`
over an in-memory limiter (``get_rate_limit_service`` override), so no LLM / Redis / HF wiring
runs. Asserts:

* a caller cannot chat into a ``session_id`` that is not their own (``403``);
* a guest is stopped at the boundary on the 11th message (10th ``200``, 11th ``429`` with an
  upgrade-prompting message + ``Retry-After``);
* a rejected cross-session request does not consume the rate budget.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import httpx
from httpx import ASGITransport

from app.api.chat import get_chat_service
from app.llm.types import ChatMessage
from app.main import app
from app.schemas.chat import ChatEvent, DoneEvent, StartEvent, TokenEvent
from app.security.dependencies import get_rate_limit_service, require_auth
from app.services.rate_limiting import InMemoryRateLimiter, RateLimitService
from tests.fakes import fake_current_user


class _FakeService:
    async def stream_turn(
        self,
        session_id: str,
        message: str,
        *,
        history: Sequence[ChatMessage] | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        yield StartEvent(message_id="m1")
        yield TokenEvent(content="Hi")
        yield DoneEvent(message_id="m1", finish_reason="stop")


def _guest_rate_limit_service(*, guest_message_limit: int = 10) -> RateLimitService:
    return RateLimitService(
        InMemoryRateLimiter(),
        guest_message_limit=guest_message_limit,
        guest_upload_limit=1,
        guest_window_seconds=86_400,
        user_message_limit=10**9,
        user_upload_limit=10**9,
        user_window_seconds=3600,
    )


async def test_chat_denies_other_users_session() -> None:
    fake = _FakeService()
    service = _guest_rate_limit_service()
    app.dependency_overrides[get_chat_service] = lambda: fake
    # Caller owns "mine" but the request names "other" → own-data-only → 403.
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "mine", role="user", user_id="u1"
    )
    app.dependency_overrides[get_rate_limit_service] = lambda: service
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/chat", json={"session_id": "other", "message": "hello"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_guest_eleventh_message_is_rate_limited() -> None:
    fake = _FakeService()
    service = _guest_rate_limit_service(guest_message_limit=10)
    app.dependency_overrides[get_chat_service] = lambda: fake
    app.dependency_overrides[require_auth] = lambda: fake_current_user("s1", role="guest")
    app.dependency_overrides[get_rate_limit_service] = lambda: service
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # First 10 messages are allowed.
            for _ in range(10):
                ok = await client.post("/api/chat", json={"session_id": "s1", "message": "hi"})
                assert ok.status_code == 200

            # The 11th is rejected before any stream opens.
            denied = await client.post("/api/chat", json={"session_id": "s1", "message": "hi"})
    finally:
        app.dependency_overrides.clear()

    assert denied.status_code == 429
    assert "Sign in" in denied.json()["detail"]  # prompts upgrade-to-account
    assert "Retry-After" in denied.headers


async def test_rejected_cross_session_request_does_not_consume_budget() -> None:
    # A 403'd request must not count toward the caller's own budget (authz before rate-limit).
    fake = _FakeService()
    service = _guest_rate_limit_service(guest_message_limit=1)
    app.dependency_overrides[get_chat_service] = lambda: fake
    app.dependency_overrides[require_auth] = lambda: fake_current_user("s1", role="guest")
    app.dependency_overrides[get_rate_limit_service] = lambda: service
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Wrong session → 403, budget untouched.
            forbidden = await client.post(
                "/api/chat", json={"session_id": "not-mine", "message": "hi"}
            )
            assert forbidden.status_code == 403
            # The one allowed message on the caller's own session still goes through.
            ok = await client.post("/api/chat", json={"session_id": "s1", "message": "hi"})
    finally:
        app.dependency_overrides.clear()

    assert ok.status_code == 200
