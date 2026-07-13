"""End-to-end tests for the topic guardrail (P6-04, design §7.4).

The planner's intent classification *is* the topic guardrail (no extra LLM call). These tests
drive the **real** :class:`GraphTurnStreamer` behind :class:`ChatService` with a scripted
planner completer, and assert:

* an ``OFF_TOPIC`` turn streams the generic refusal as a normal ``start`` → ``token`` → ``done``
  turn (finish reason ``off_topic``) and the **responder LLM is never invoked**, and
* a ``JOB_HUNTING`` turn is **not** short-circuited — the responder runs (it frames the
  market-requirements redirect).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from app.agents.graph import OFF_TOPIC_REFUSAL, GraphTurnStreamer
from app.agents.planner import PLANNER_TOOL_NAME
from app.llm.types import ChatMessage, CompletionResult, FunctionCall, ToolCall, ToolSchema
from app.schemas.chat import (
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    TokenEvent,
)
from app.services.chat import ChatService
from app.services.session_memory import InMemorySessionMemory
from tests.fakes import FakeResponderRouter


class _PlannerCompleter:
    """A scripted planner ``LLMCompleter`` that forces ``record_plan`` with a fixed intent."""

    def __init__(self, intent: str) -> None:
        self._intent = intent

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = None,
        tool_choice: Any = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        args = json.dumps({"intent": self._intent, "steps": ["handle the turn"]})
        return CompletionResult(
            content=None,
            tool_calls=[
                ToolCall(id="c1", function=FunctionCall(name=PLANNER_TOOL_NAME, arguments=args))
            ],
            finish_reason="tool_calls",
            model="fake",
        )


async def _collect(service: ChatService, session: str, message: str) -> list[ChatEvent]:
    return [event async for event in service.stream_turn(session, message)]


async def test_off_topic_turn_streams_refusal_without_calling_the_responder() -> None:
    responder_router = FakeResponderRouter()
    streamer = GraphTurnStreamer(
        responder_router=responder_router, router=_PlannerCompleter("off_topic")
    )
    service = ChatService(streamer, InMemorySessionMemory())

    events = await _collect(service, "s1", "Is this rash serious?")

    assert not any(isinstance(e, ErrorEvent) for e in events)
    tokens = "".join(e.content for e in events if isinstance(e, TokenEvent))
    assert tokens == OFF_TOPIC_REFUSAL
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].finish_reason == "off_topic"
    # The responder LLM was never invoked for a refused off-topic turn.
    assert responder_router.stream_messages == []
    assert responder_router.complete_messages == []


async def test_job_hunting_turn_is_not_short_circuited() -> None:
    """A job-hunting turn runs the responder (it composes the redirect), unlike off-topic."""
    responder_router = FakeResponderRouter(content="Here's what the market wants instead.")
    streamer = GraphTurnStreamer(
        responder_router=responder_router, router=_PlannerCompleter("job_hunting")
    )
    service = ChatService(streamer, InMemorySessionMemory())

    events = await _collect(service, "s1", "find me AI architect jobs in Berlin")

    assert not any(isinstance(e, ErrorEvent) for e in events)
    tokens = "".join(e.content for e in events if isinstance(e, TokenEvent))
    assert tokens == "Here's what the market wants instead."
    # The responder DID run — a job-hunting turn is redirected, not refused/short-circuited.
    assert responder_router.stream_messages != []
