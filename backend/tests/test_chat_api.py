"""API smoke test for ``POST /api/chat`` (P1-04, extended with P3-04 auth/rate-limit).

Overrides the :func:`~app.api.chat.get_chat_service` dependency with a fake service that
yields canned events, plus ``require_auth`` (authenticated caller) and
``get_rate_limit_service`` (in-memory, uncapped), so the real LLM router / Redis / HF wiring
never runs. Asserts the endpoint returns a valid ``text/event-stream`` with correctly framed
SSE events.
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
from tests.fakes import fake_current_user, unlimited_rate_limit_service


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


async def test_chat_endpoint_streams_sse() -> None:
    app.dependency_overrides[get_chat_service] = lambda: _FakeService()
    app.dependency_overrides[require_auth] = lambda: fake_current_user("s1")
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/chat", json={"session_id": "s1", "message": "hello"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: start" in body
    assert "event: token" in body
    assert '"content": "Hi"' in body
    assert "event: done" in body


async def test_chat_endpoint_rejects_empty_message() -> None:
    # With an authenticated caller, body validation is what must reject the empty message.
    app.dependency_overrides[require_auth] = lambda: fake_current_user("s1")
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/chat", json={"session_id": "s1", "message": ""})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422


async def test_chat_endpoint_requires_auth() -> None:
    # No Authorization header and no override → the auth guard rejects before streaming.
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/chat", json={"session_id": "s1", "message": "hello"})
    assert response.status_code == 401
