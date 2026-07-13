"""Unit tests for the graph-driven chat service (P4-07).

Drives :class:`~app.services.chat.ChatService` with a **fake** ``GraphTurnRunner``
(:class:`tests.fakes.FakeGraphRunner`) — no HF network, no Redis, no LangGraph. Covers the
contracts the service owns around the multi-agent graph:

* a plain-answer path: ``start`` → ``plan`` → token-by-token ``token`` → ``done`` + memory
  replay across turns,
* the ``plan`` event surfaces the planner's intent + which workers ran (visible steps),
* a worker-routed turn produces both streamed tokens and non-empty ``done`` citations,
* the terminal-error safety net (an unexpected graph failure → a single ``error`` event).
"""

from __future__ import annotations

from typing import Any

from app.agents.state import Citation, Intent, PlannerDecision, WorkerName
from app.llm.errors import LLMAllModelsFailedError
from app.llm.types import StreamChunk
from app.schemas.chat import (
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    PlanEvent,
    StartEvent,
    TokenEvent,
)
from app.services.chat import ChatService
from app.services.session_memory import InMemorySessionMemory
from tests.fakes import FakeGraphRunner

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _service(runner: FakeGraphRunner, **kwargs: Any) -> ChatService:
    return ChatService(runner, InMemorySessionMemory(), **kwargs)


async def _collect(service: ChatService, session: str, message: str) -> list[ChatEvent]:
    return [event async for event in service.stream_turn(session, message)]


# --------------------------------------------------------------------------- #
# (a) plain answer + streaming + memory
# --------------------------------------------------------------------------- #
async def test_plain_answer_streams_tokens_and_finishes() -> None:
    runner = FakeGraphRunner(
        [[StreamChunk(content="Hello"), StreamChunk(content=" world", finish_reason="stop")]]
    )
    service = _service(runner)

    events = await _collect(service, "s1", "hi")

    assert isinstance(events[0], StartEvent)
    tokens = [e.content for e in events if isinstance(e, TokenEvent)]
    assert tokens == ["Hello", " world"]
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].finish_reason == "stop"
    # message_id is stable start ↔ done, and was threaded into the graph state.
    assert events[0].message_id == events[-1].message_id
    assert runner.plan_states[0].message_id == events[0].message_id


async def test_history_is_replayed_on_the_next_turn() -> None:
    memory = InMemorySessionMemory()
    runner = FakeGraphRunner(
        [
            [StreamChunk(content="one", finish_reason="stop")],
            [StreamChunk(content="two", finish_reason="stop")],
        ]
    )
    service = ChatService(runner, memory)

    _ = [e async for e in service.stream_turn("s1", "first")]
    _ = [e async for e in service.stream_turn("s1", "second")]

    # The second turn's graph state must carry the first turn's user + assistant messages as
    # its history slice, with the new user message as the current turn.
    second = runner.plan_states[1]
    history_contents = [m.content for m in second.history]
    assert "first" in history_contents
    assert "one" in history_contents
    assert second.user_message == "second"


# --------------------------------------------------------------------------- #
# (b) plan event surfaces intent + workers that ran
# --------------------------------------------------------------------------- #
async def test_plan_event_surfaces_intent_and_workers() -> None:
    runner = FakeGraphRunner(
        plan=PlannerDecision(
            intent=Intent.MARKET_REQUIREMENTS,
            steps=["find roles", "match to CV"],
            workers=[WorkerName.RAG, WorkerName.MARKET_INTEL],
        )
    )
    service = _service(runner)

    events = await _collect(service, "s1", "find me a job")

    plans = [e for e in events if isinstance(e, PlanEvent)]
    assert len(plans) == 1
    plan = plans[0]
    assert plan.intent == "market_requirements"
    assert plan.steps == ["find roles", "match to CV"]
    assert plan.workers == ["rag", "market_intel"]
    # The plan lands after start and before any token (visible steps before the answer).
    order = [type(e).__name__ for e in events]
    assert order.index("PlanEvent") < order.index("TokenEvent")


# --------------------------------------------------------------------------- #
# (c) a worker-routed turn yields tokens AND citations end-to-end
# --------------------------------------------------------------------------- #
async def test_worker_turn_streams_tokens_and_cites_sources() -> None:
    runner = FakeGraphRunner(
        [[StreamChunk(content="Grounded answer [1].", finish_reason="stop")]],
        plan=PlannerDecision(intent=Intent.CV_QUESTION, workers=[WorkerName.RAG]),
        citations=[Citation(worker=WorkerName.RAG, title="rag-source", url="https://kb/1")],
    )
    service = _service(runner)

    events = await _collect(service, "s1", "what should I improve?")

    assert [e.content for e in events if isinstance(e, TokenEvent)] == ["Grounded answer [1]."]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert len(done.citations) == 1
    assert done.citations[0].title == "rag-source"
    assert done.citations[0].url == "https://kb/1"
    assert done.citations[0].worker == "rag"


# --------------------------------------------------------------------------- #
# (d) terminal-error safety net (an unexpected graph failure)
# --------------------------------------------------------------------------- #
async def test_all_models_failed_surfaces_terminal_error() -> None:
    # The real graph nodes fail soft; a raw LLMAllModelsFailedError escaping the runner models
    # an infrastructure failure the service must convert to a single terminal error event.
    runner = FakeGraphRunner(plan_error=LLMAllModelsFailedError("all down"))
    service = _service(runner)

    events = await _collect(service, "s1", "hi")

    assert isinstance(events[0], StartEvent)
    assert isinstance(events[-1], ErrorEvent)
    assert "unavailable" in events[-1].message.lower()
    assert not any(isinstance(e, DoneEvent) for e in events)


async def test_unexpected_error_surfaces_terminal_error() -> None:
    runner = FakeGraphRunner(plan_error=RuntimeError("boom"))
    service = _service(runner)

    events = await _collect(service, "s1", "hi")

    assert isinstance(events[-1], ErrorEvent)
    assert not any(isinstance(e, DoneEvent) for e in events)
