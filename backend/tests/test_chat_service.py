"""Unit tests for the chat tool-call loop service (P1-04).

Drives :class:`~app.services.chat.ChatService` with a **fake** LLM router and tool
registry — no HF network, no Redis, no real tools. Covers:

* a plain-answer path (no tool call) + token-by-token streaming + memory replay,
* a tool-call round trip (one tool call, then a final answer),
* the iteration cap triggering on a model that never stops calling tools,
* an all-models-failed router error surfacing as a single terminal ``error`` event.
"""

from __future__ import annotations

from typing import Any

from app.llm.errors import LLMAllModelsFailedError
from app.llm.types import StreamChunk, ToolCallDelta
from app.schemas.chat import (
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    StartEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from app.services.chat import ChatService
from app.services.session_memory import InMemorySessionMemory
from tests.fakes import FakeRegistry, FakeRouter, Script

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _service(
    router: FakeRouter, registry: FakeRegistry | None = None, **kwargs: Any
) -> ChatService:
    return ChatService(router, registry or FakeRegistry(), InMemorySessionMemory(), **kwargs)  # type: ignore[arg-type]


async def _collect(service: ChatService, session: str, message: str) -> list[ChatEvent]:
    return [event async for event in service.stream_turn(session, message)]


def _tool_delta(index: int, **kwargs: Any) -> StreamChunk:
    return StreamChunk(tool_call_deltas=[ToolCallDelta(index=index, **kwargs)])


# --------------------------------------------------------------------------- #
# (a) plain answer + streaming + memory
# --------------------------------------------------------------------------- #
async def test_plain_answer_streams_tokens_and_finishes() -> None:
    router = FakeRouter(
        [[StreamChunk(content="Hello"), StreamChunk(content=" world", finish_reason="stop")]]
    )
    service = _service(router)

    events = await _collect(service, "s1", "hi")

    assert isinstance(events[0], StartEvent)
    tokens = [e.content for e in events if isinstance(e, TokenEvent)]
    assert tokens == ["Hello", " world"]
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].finish_reason == "stop"
    # message_id is stable start ↔ done.
    assert events[0].message_id == events[-1].message_id
    # No tool events on the plain path.
    assert not any(isinstance(e, (ToolCallEvent, ToolResultEvent)) for e in events)


async def test_history_is_replayed_on_the_next_turn() -> None:
    memory = InMemorySessionMemory()
    router = FakeRouter(
        [
            [StreamChunk(content="one", finish_reason="stop")],
            [StreamChunk(content="two", finish_reason="stop")],
        ]
    )
    service = ChatService(router, FakeRegistry(), memory)  # type: ignore[arg-type]

    _ = [e async for e in service.stream_turn("s1", "first")]
    _ = [e async for e in service.stream_turn("s1", "second")]

    # The second model call must include the first turn's user + assistant messages.
    second_call = router.calls[1]
    contents = [m.content for m in second_call]
    assert "first" in contents
    assert "one" in contents
    assert "second" in contents


# --------------------------------------------------------------------------- #
# (b) tool-call round trip
# --------------------------------------------------------------------------- #
async def test_tool_call_round_trip() -> None:
    router = FakeRouter(
        [
            # 1st completion: the model streams a tool call in two deltas.
            [
                _tool_delta(0, id="call_1", name="current_date_and_time", arguments=""),
                StreamChunk(
                    tool_call_deltas=[ToolCallDelta(index=0, arguments="{}")],
                    finish_reason="tool_calls",
                ),
            ],
            # 2nd completion: the model answers using the tool result.
            [StreamChunk(content="It is noon.", finish_reason="stop")],
        ]
    )
    registry = FakeRegistry(result='{"now": "noon"}')
    service = _service(router, registry)

    events = await _collect(service, "s1", "what time is it")

    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "current_date_and_time"
    assert tool_calls[0].arguments == "{}"
    assert tool_results[0].tool_call_id == "call_1"
    assert tool_results[0].content == '{"now": "noon"}'
    # Final answer streamed after the tool result.
    assert any(isinstance(e, TokenEvent) and e.content == "It is noon." for e in events)
    assert isinstance(events[-1], DoneEvent)

    # The reassembled tool call reached the registry with merged arguments.
    assert registry.executed[0].id == "call_1"
    assert registry.executed[0].function.arguments == "{}"
    # The 2nd model call includes the assistant tool-call request + the tool reply.
    roles = [m.role for m in router.calls[1]]
    assert "tool" in roles


# --------------------------------------------------------------------------- #
# (c) iteration cap
# --------------------------------------------------------------------------- #
async def test_iteration_cap_stops_runaway_tool_calls() -> None:
    # A model that always asks for a tool, never answering.
    always_tool: Script = [
        _tool_delta(0, id="call_x", name="current_date_and_time", arguments="{}"),
        StreamChunk(finish_reason="tool_calls"),
    ]
    router = FakeRouter(always=always_tool)
    service = _service(router, max_iterations=2)

    events = await _collect(service, "s1", "loop forever")

    # Exactly max_iterations tool calls, then a terminal error, no DoneEvent.
    assert len([e for e in events if isinstance(e, ToolCallEvent)]) == 2
    assert isinstance(events[-1], ErrorEvent)
    assert not any(isinstance(e, DoneEvent) for e in events)


# --------------------------------------------------------------------------- #
# (d) all-models-failed → terminal error event
# --------------------------------------------------------------------------- #
async def test_all_models_failed_surfaces_terminal_error() -> None:
    router = FakeRouter([LLMAllModelsFailedError("all down")])
    service = _service(router)

    events = await _collect(service, "s1", "hi")

    assert isinstance(events[0], StartEvent)
    assert isinstance(events[-1], ErrorEvent)
    assert "unavailable" in events[-1].message.lower()
    assert not any(isinstance(e, DoneEvent) for e in events)
