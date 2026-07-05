"""API smoke test for ``POST /api/chat`` (P1-04).

Overrides the :func:`~app.api.chat.get_chat_service` dependency with a fake service
that yields canned events, so the real LLM router / Redis / HF wiring never runs.
Asserts the endpoint returns a valid ``text/event-stream`` with correctly framed SSE
events.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import httpx
from httpx import ASGITransport

from app.api.chat import get_chat_service
from app.llm.types import ChatMessage
from app.main import app
from app.schemas.chat import ChatEvent, DoneEvent, StartEvent, TokenEvent


class _FakeService:
    async def stream_turn(
        self,
        session_id: str,
        message: str,
        *,
        history: Sequence[ChatMessage] | None = None,
    ) -> AsyncIterator[ChatEvent]:
        yield StartEvent(message_id="m1")
        yield TokenEvent(content="Hi")
        yield DoneEvent(message_id="m1", finish_reason="stop")


async def test_chat_endpoint_streams_sse() -> None:
    app.dependency_overrides[get_chat_service] = lambda: _FakeService()
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/chat", json={"session_id": "s1", "message": "hello"})
    finally:
        app.dependency_overrides.pop(get_chat_service, None)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: start" in body
    assert "event: token" in body
    assert '"content": "Hi"' in body
    assert "event: done" in body


async def test_chat_endpoint_rejects_empty_message() -> None:
    # Validation happens before the service, so no override is needed.
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/chat", json={"session_id": "s1", "message": ""})
    assert response.status_code == 422
