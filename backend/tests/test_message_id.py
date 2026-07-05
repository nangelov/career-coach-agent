"""Unit tests for the stable, feedback-ready ``message_id`` (P1-07).

Design §5.5: *"each assistant message carries a stable ``message_id``"*. These tests
pin the guarantees P2's ``message_feedback`` table and P9's
``POST /api/messages/{message_id}/feedback`` will depend on:

* the id is assigned once per turn and is identical across every ``message_id``-bearing
  SSE event (``start`` ↔ ``done``/``cancelled``),
* two turns — including two turns in the **same** session — get different ids,
* the id survives a round trip through ``SessionMemory`` (``append`` → ``load``), both
  the in-memory store and the Redis-backed JSON store, and is recoverable via
  :meth:`SessionMemory.get_message`,
* a cancelled turn's persisted partial answer keeps the id it streamed under,
* the id **never** leaks into the payload sent to the LLM provider
  (:meth:`ChatMessage.to_openai`).

Everything runs against fakes — no HF network, no real Redis.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.llm.types import ChatMessage, StreamChunk, ToolCallDelta
from app.repositories.redis import RedisSessionMemory
from app.schemas.chat import (
    CancelledEvent,
    ChatEvent,
    DoneEvent,
    StartEvent,
)
from app.services.cancellation import InMemoryCancelRegistry
from app.services.chat import ChatService
from app.services.session_memory import InMemorySessionMemory, SessionMemory
from tests.fakes import FakeRegistry, FakeRouter

# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _CancelMidStream(InMemoryCancelRegistry):
    """Reports a cancel only *after* the turn's first ``is_requested`` poll.

    ``stream_turn`` polls once at the iteration boundary (before streaming) and again
    every N chunks *during* the completion. Returning ``False`` on the first poll and
    ``True`` afterwards models a client that hits the stop button once the stream is
    already underway — so the turn produces a partial answer, then stops.
    """

    def __init__(self, *, fire_on_call: int = 2) -> None:
        super().__init__()
        self._calls = 0
        self._fire_on_call = fire_on_call

    async def is_requested(self, session_id: str) -> bool:
        self._calls += 1
        return self._calls >= self._fire_on_call


def _service(
    router: FakeRouter,
    memory: SessionMemory | None = None,
    *,
    cancel: InMemoryCancelRegistry | None = None,
    **kwargs: Any,
) -> ChatService:
    return ChatService(
        router,  # type: ignore[arg-type]
        FakeRegistry(),
        memory or InMemorySessionMemory(),
        cancel,
        **kwargs,
    )


async def _collect(service: ChatService, session: str, message: str) -> list[ChatEvent]:
    return [event async for event in service.stream_turn(session, message)]


def _ids(events: Sequence[ChatEvent]) -> list[str]:
    """Every ``message_id`` carried by the events (start/done/cancelled bear one)."""
    return [e.message_id for e in events if hasattr(e, "message_id")]


def _tool_delta(index: int, **kwargs: Any) -> StreamChunk:
    return StreamChunk(tool_call_deltas=[ToolCallDelta(index=index, **kwargs)])


# --------------------------------------------------------------------------- #
# (a) stable across every event of one turn
# --------------------------------------------------------------------------- #
async def test_message_id_identical_across_all_sse_events_of_a_turn() -> None:
    router = FakeRouter(
        [[StreamChunk(content="Hello"), StreamChunk(content=" world", finish_reason="stop")]]
    )
    events = await _collect(_service(router), "s1", "hi")

    ids = _ids(events)
    # start + done both carry the id; both must be the same single value.
    assert len(ids) == 2
    assert ids[0] == ids[1]
    assert isinstance(events[0], StartEvent)
    assert isinstance(events[-1], DoneEvent)
    assert events[0].message_id == events[-1].message_id


async def test_message_id_stable_across_a_tool_call_turn() -> None:
    router = FakeRouter(
        [
            [
                _tool_delta(0, id="call_1", name="current_date_and_time", arguments="{}"),
                StreamChunk(finish_reason="tool_calls"),
            ],
            [StreamChunk(content="It is noon.", finish_reason="stop")],
        ]
    )
    events = await _collect(_service(router), "s1", "time?")

    ids = _ids(events)
    assert len(set(ids)) == 1  # one id spans the whole multi-iteration turn


# --------------------------------------------------------------------------- #
# (b) distinct across turns (including within one session)
# --------------------------------------------------------------------------- #
async def test_two_turns_same_session_get_distinct_ids() -> None:
    memory = InMemorySessionMemory()
    router = FakeRouter(
        [
            [StreamChunk(content="one", finish_reason="stop")],
            [StreamChunk(content="two", finish_reason="stop")],
        ]
    )
    service = _service(router, memory)

    first = await _collect(service, "s1", "first")
    second = await _collect(service, "s1", "second")

    assert _ids(first)[0] != _ids(second)[0]


async def test_two_sessions_get_distinct_ids() -> None:
    router = FakeRouter(
        [
            [StreamChunk(content="a", finish_reason="stop")],
            [StreamChunk(content="b", finish_reason="stop")],
        ]
    )
    service = _service(router)

    a = await _collect(service, "sA", "x")
    b = await _collect(service, "sB", "y")

    assert _ids(a)[0] != _ids(b)[0]


# --------------------------------------------------------------------------- #
# (c) survives the session-memory round trip
# --------------------------------------------------------------------------- #
async def test_message_id_round_trips_through_in_memory_store() -> None:
    memory = InMemorySessionMemory()
    router = FakeRouter([[StreamChunk(content="answer", finish_reason="stop")]])
    events = await _collect(_service(router, memory), "s1", "q")
    done = events[-1]
    assert isinstance(done, DoneEvent)

    stored = await memory.load("s1")
    assistant = [m for m in stored if m.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].message_id == done.message_id

    # The accessor recovers the exact message by its id.
    found = await memory.get_message("s1", done.message_id)
    assert found is not None
    assert found.content == "answer"
    assert await memory.get_message("s1", "does-not-exist") is None


async def test_message_id_survives_redis_json_round_trip() -> None:
    """The Redis store serialises via JSON — prove the id survives that, not just refs."""
    from tests.test_session_memory import FakeListRedis

    memory = RedisSessionMemory(FakeListRedis(), ttl_seconds=3600, max_messages=100)
    router = FakeRouter([[StreamChunk(content="answer", finish_reason="stop")]])

    events = await _collect(_service(router, memory), "s1", "q")
    done = events[-1]
    assert isinstance(done, DoneEvent)

    stored = await memory.load("s1")  # re-parsed from JSON strings
    assistant = [m for m in stored if m.role == "assistant"]
    assert assistant[0].message_id == done.message_id
    found = await memory.get_message("s1", done.message_id)
    assert found is not None and found.content == "answer"


# --------------------------------------------------------------------------- #
# (d) cancelled turn keeps the id it streamed under
# --------------------------------------------------------------------------- #
async def test_cancelled_partial_keeps_streamed_message_id() -> None:
    memory = InMemorySessionMemory()
    # A long single completion so the mid-stream cancel poll fires before it ends.
    router = FakeRouter([[StreamChunk(content=f"tok{i}") for i in range(20)]])
    service = _service(router, memory, cancel=_CancelMidStream(), cancel_check_interval=1)

    events = await _collect(service, "s1", "stream please")

    start = events[0]
    cancelled = events[-1]
    assert isinstance(start, StartEvent)
    assert isinstance(cancelled, CancelledEvent)
    assert start.message_id == cancelled.message_id

    # The persisted partial answer carries that same streamed id.
    stored = await memory.load("s1")
    partial = [m for m in stored if m.role == "assistant"]
    assert partial and partial[0].message_id == cancelled.message_id
    recovered = await memory.get_message("s1", cancelled.message_id)
    assert recovered is not None and recovered.role == "assistant"


# --------------------------------------------------------------------------- #
# (e) never leaks into the provider payload
# --------------------------------------------------------------------------- #
def test_message_id_excluded_from_to_openai() -> None:
    msg = ChatMessage(role="assistant", content="hi", message_id="abc123")
    wire = msg.to_openai()
    assert "message_id" not in wire
    assert wire == {"role": "assistant", "content": "hi"}


async def test_message_id_never_sent_to_provider_across_turns() -> None:
    """A 2nd turn replays the 1st turn's stored assistant message; none of the messages
    the router (provider) receives may carry ``message_id`` in their wire form."""
    memory = InMemorySessionMemory()
    router = FakeRouter(
        [
            [StreamChunk(content="one", finish_reason="stop")],
            [StreamChunk(content="two", finish_reason="stop")],
        ]
    )
    service = _service(router, memory)

    await _collect(service, "s1", "first")
    await _collect(service, "s1", "second")

    # The 2nd model call includes the 1st turn's persisted assistant answer (which now
    # carries a message_id) — but its wire rendering must not expose it.
    for call in router.calls:
        for message in call:
            assert "message_id" not in message.to_openai()
