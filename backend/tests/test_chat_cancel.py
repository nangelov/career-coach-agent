"""Unit tests for the Redis-backed cancel/stop signal (P1-06).

Three layers, all with fakes/doubles — no real Redis, no HF network:

* :class:`~app.repositories.redis.RedisCancelRegistry` against an in-memory
  ``FakeCancelRedis`` (set-with-TTL, exists, delete; TTL from settings).
* :class:`~app.services.chat.ChatService` cancellation behaviour: a cancel observed
  mid-stream stops and emits a terminal ``cancelled`` event; a cancel observed between
  tool round-trips stops before the next model call; a turn that finishes before any
  cancel is unaffected; two ``session_id``s never cross-cancel; a stale flag from a
  prior turn is cleared at the start of a new one.
* ``POST /api/chat/{session}/cancel`` returns promptly (202) and delegates to the
  service without touching any stream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
from httpx import ASGITransport

from app.api.chat import get_chat_service
from app.llm.types import ChatMessage, StreamChunk, ToolCallDelta
from app.main import app
from app.repositories.redis import RedisCancelRegistry
from app.schemas.chat import (
    CancelledEvent,
    ChatEvent,
    DoneEvent,
    StartEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from app.services.cancellation import CancelRegistry, InMemoryCancelRegistry
from app.services.chat import ChatService
from app.services.session_memory import InMemorySessionMemory


# --------------------------------------------------------------------------- #
# Fake Redis (cancel key surface) + registry unit tests
# --------------------------------------------------------------------------- #
class FakeCancelRedis:
    """In-memory async stand-in for the key subset the cancel registry uses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, name: str, value: Any, *, ex: int | None = None) -> bool:
        self.store[name] = str(value)
        if ex is not None:
            self.ttls[name] = ex
        return True

    async def exists(self, *names: str) -> int:
        return sum(1 for name in names if name in self.store)

    async def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            if self.store.pop(name, None) is not None:
                removed += 1
            self.ttls.pop(name, None)
        return removed


async def test_registry_request_sets_flag_with_ttl() -> None:
    fake = FakeCancelRedis()
    registry = RedisCancelRegistry(fake, ttl_seconds=42)

    await registry.request("s1")

    assert await registry.is_requested("s1") is True
    assert fake.store["session:cancel:s1"] == "1"
    assert fake.ttls["session:cancel:s1"] == 42


async def test_registry_is_requested_false_when_unset() -> None:
    registry = RedisCancelRegistry(FakeCancelRedis())
    assert await registry.is_requested("never") is False


async def test_registry_clear_deletes_flag() -> None:
    fake = FakeCancelRedis()
    registry = RedisCancelRegistry(fake)

    await registry.request("s1")
    await registry.clear("s1")

    assert await registry.is_requested("s1") is False
    assert "session:cancel:s1" not in fake.store


async def test_registry_from_settings_uses_configured_ttl() -> None:
    from app.config import settings

    fake = FakeCancelRedis()
    registry = RedisCancelRegistry.from_settings(fake, settings)

    await registry.request("s1")
    assert fake.ttls["session:cancel:s1"] == settings.CHAT_CANCEL_TTL_SECONDS


async def test_registry_sessions_are_isolated() -> None:
    registry = RedisCancelRegistry(FakeCancelRedis())
    await registry.request("s1")
    assert await registry.is_requested("s1") is True
    assert await registry.is_requested("s2") is False


# --------------------------------------------------------------------------- #
# ChatService cancellation
# --------------------------------------------------------------------------- #
class _Router:
    """Scripted router: one stream (list of chunks) per turn."""

    def __init__(self, scripts: Sequence[list[StreamChunk]]) -> None:
        self._scripts = list(scripts)
        self.calls = 0

    async def stream(self, messages: Sequence[ChatMessage], **_: Any) -> AsyncIterator[StreamChunk]:
        idx = self.calls
        self.calls += 1
        for chunk in self._scripts[idx]:
            yield chunk

    async def aclose(self) -> None:
        pass


class _Registry:
    """Tool registry returning one canned tool reply per executed call."""

    def schemas(self) -> list[dict[str, Any]]:
        return []

    async def execute(self, tool_call: Any) -> ChatMessage:
        return ChatMessage(
            role="tool",
            content='{"ok": true}',
            name=tool_call.function.name,
            tool_call_id=tool_call.id,
        )


class _TrippingCancel(CancelRegistry):
    """Cancel registry that reports "requested" after ``trip_after`` polls.

    Simulates a cancel arriving mid-stream: the first ``trip_after`` calls to
    :meth:`is_requested` return ``False``, subsequent ones return ``True`` (until a
    :meth:`clear`). Records clears so tests can assert the flag was cleaned up.
    """

    def __init__(self, trip_after: int) -> None:
        self._trip_after = trip_after
        self.polls = 0
        self.cleared = 0
        self._forced = False

    async def request(self, session_id: str) -> None:
        self._forced = True

    async def is_requested(self, session_id: str) -> bool:
        self.polls += 1
        return self._forced or self.polls > self._trip_after

    async def clear(self, session_id: str) -> None:
        self.cleared += 1


async def _collect(service: ChatService, session: str, message: str) -> list[ChatEvent]:
    return [event async for event in service.stream_turn(session, message)]


async def test_cancel_mid_stream_stops_and_emits_cancelled() -> None:
    # A long single completion; cancel trips after 2 polls (loop-top + one chunk).
    router = _Router([[StreamChunk(content=f"tok{i}") for i in range(20)]])
    cancel = _TrippingCancel(trip_after=2)
    memory = InMemorySessionMemory()
    service = ChatService(router, _Registry(), memory, cancel, cancel_check_interval=1)  # type: ignore[arg-type]

    events = await _collect(service, "s1", "hi")

    assert isinstance(events[0], StartEvent)
    assert isinstance(events[-1], CancelledEvent)
    assert events[-1].message_id == events[0].message_id
    # Stopped early — far fewer than the 20 scripted tokens streamed.
    tokens = [e for e in events if isinstance(e, TokenEvent)]
    assert 0 < len(tokens) < 20
    assert not any(isinstance(e, DoneEvent) for e in events)
    # Flag was cleared on finish, and the partial answer persisted for continuity.
    assert cancel.cleared >= 1
    stored = await memory.load("s1")
    assert stored[0].content == "hi"
    assert stored[-1].role == "assistant"
    assert stored[-1].content == "".join(e.content for e in tokens)


async def test_cancel_between_tool_round_trips_stops_before_next_call() -> None:
    # 1st stream asks for a tool; the router requests cancel right after, so the
    # iteration-boundary check stops the loop before a 2nd model call.
    tool_stream = [
        StreamChunk(
            tool_call_deltas=[ToolCallDelta(index=0, id="call_1", name="now", arguments="{}")],
            finish_reason="tool_calls",
        ),
    ]
    answer_stream = [StreamChunk(content="should not be reached", finish_reason="stop")]
    cancel = InMemoryCancelRegistry()

    class _RouterThenCancel(_Router):
        async def stream(
            self, messages: Sequence[ChatMessage], **kw: Any
        ) -> AsyncIterator[StreamChunk]:
            first = self.calls == 0
            async for chunk in super().stream(messages, **kw):
                yield chunk
            if first:
                await cancel.request("s1")

    router = _RouterThenCancel([tool_stream, answer_stream])
    service = ChatService(router, _Registry(), InMemorySessionMemory(), cancel)  # type: ignore[arg-type]

    events = await _collect(service, "s1", "what time is it")

    assert len([e for e in events if isinstance(e, ToolCallEvent)]) == 1
    assert len([e for e in events if isinstance(e, ToolResultEvent)]) == 1
    assert isinstance(events[-1], CancelledEvent)
    assert not any(isinstance(e, DoneEvent) for e in events)
    # The 2nd (answer) stream was never opened.
    assert router.calls == 1


async def test_turn_without_cancel_completes_normally() -> None:
    router = _Router([[StreamChunk(content="hello", finish_reason="stop")]])
    cancel = InMemoryCancelRegistry()
    service = ChatService(router, _Registry(), InMemorySessionMemory(), cancel)  # type: ignore[arg-type]

    events = await _collect(service, "s1", "hi")

    assert isinstance(events[-1], DoneEvent)
    assert not any(isinstance(e, CancelledEvent) for e in events)


async def test_cancel_does_not_cross_sessions() -> None:
    router = _Router([[StreamChunk(content="hello", finish_reason="stop")]])
    cancel = InMemoryCancelRegistry()
    await cancel.request("other-session")
    service = ChatService(router, _Registry(), InMemorySessionMemory(), cancel)  # type: ignore[arg-type]

    events = await _collect(service, "s1", "hi")

    # s1 is unaffected by a cancel targeting a different session.
    assert isinstance(events[-1], DoneEvent)
    assert await cancel.is_requested("other-session") is True


async def test_stale_flag_is_cleared_at_turn_start() -> None:
    # A cancel flag left set before the turn begins must not abort the new turn.
    router = _Router([[StreamChunk(content="fresh answer", finish_reason="stop")]])
    cancel = InMemoryCancelRegistry()
    await cancel.request("s1")  # stale flag from a prior, finished turn
    service = ChatService(router, _Registry(), InMemorySessionMemory(), cancel)  # type: ignore[arg-type]

    events = await _collect(service, "s1", "hi")

    assert isinstance(events[-1], DoneEvent)
    assert not any(isinstance(e, CancelledEvent) for e in events)


# --------------------------------------------------------------------------- #
# Cancel endpoint (returns promptly, delegates to the service)
# --------------------------------------------------------------------------- #
class _FakeService:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    async def request_cancel(self, session_id: str) -> None:
        self.cancelled.append(session_id)


async def test_cancel_endpoint_returns_promptly_and_delegates() -> None:
    fake = _FakeService()
    app.dependency_overrides[get_chat_service] = lambda: fake
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/chat/demo/cancel")
    finally:
        app.dependency_overrides.pop(get_chat_service, None)

    assert response.status_code == 202
    assert response.json()["session"] == "demo"
    # Delegated to the service without opening any stream.
    assert fake.cancelled == ["demo"]
