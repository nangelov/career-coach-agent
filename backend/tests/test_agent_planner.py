"""Unit + integration tests for the LLM-backed planner (P4-03, design §3).

Covers the four things the task's acceptance criteria call out:

* intent classification drives the expected (deterministic) worker routing,
* budget fields are populated with sane per-intent defaults,
* the failure path (router error / missing / malformed tool call) fails soft to a safe
  default without raising, and
* an integration test running the **real compiled graph** (``build_graph(router=...)``)
  proves the planner's decision actually drives ``route_after_planner``'s fan-out — only
  the routed workers execute.

The LLM boundary is always mocked (a :class:`FakeCompleter`); no test hits a real HF
endpoint.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest

from app.agents.graph import (
    INPUT_GUARDRAIL,
    MEMORY_RECALL,
    MEMORY_WRITER,
    OFF_TOPIC_REFUSAL,
    OUTPUT_GUARDRAIL,
    PLANNER,
    RESPONDER,
    build_graph,
)
from app.agents.planner import (
    PLANNER_TOOL_NAME,
    PLANNER_TOOL_SCHEMA,
    Planner,
    _parse_decision,
)
from app.agents.state import AgentState, Intent, WorkerName
from app.llm.errors import LLMAllModelsFailedError
from app.llm.types import (
    ChatMessage,
    CompletionResult,
    FunctionCall,
    ToolCall,
    ToolSchema,
)


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeCompleter:
    """Programmable :class:`~app.agents.planner.LLMCompleter` double.

    Returns ``result`` from :meth:`complete`, or raises ``error`` when set. Records the
    last call's ``messages`` / ``tools`` / ``tool_choice`` so tests can assert the planner
    forced the tool call correctly.
    """

    def __init__(
        self,
        *,
        result: CompletionResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.calls = 0
        self.last_messages: list[ChatMessage] = []
        self.last_tools: Sequence[ToolSchema] | None = None
        self.last_tool_choice: Any = None

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        self.calls += 1
        self.last_messages = list(messages)
        self.last_tools = tools
        self.last_tool_choice = tool_choice
        if self._error is not None:
            raise self._error
        assert self._result is not None, "FakeCompleter has no result"
        return self._result


def _tool_result(
    arguments: dict[str, Any] | str, *, name: str = PLANNER_TOOL_NAME
) -> CompletionResult:
    """A completion that forced-calls ``record_plan`` with ``arguments``."""
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return CompletionResult(
        content=None,
        tool_calls=[ToolCall(id="call_1", function=FunctionCall(name=name, arguments=raw))],
        finish_reason="tool_calls",
        model="fake",
    )


def _state(message: str = "hello", **kw: Any) -> AgentState:
    return AgentState(session_id="s", user_message=message, **kw)


async def _plan(arguments: dict[str, Any]) -> Any:
    """Run the planner once against ``arguments`` and return the decision."""
    completer = FakeCompleter(result=_tool_result(arguments))
    return await Planner(completer).plan(_state())


# --------------------------------------------------------------------------- #
# Intent → worker routing (deterministic, conservative)
# --------------------------------------------------------------------------- #
async def test_market_requirements_routes_to_market_worker() -> None:
    decision = await _plan(
        {"intent": "market_requirements", "steps": ["look up role requirements"]}
    )

    assert decision.intent is Intent.MARKET_REQUIREMENTS
    assert decision.workers == [WorkerName.MARKET_INTEL]


async def test_job_hunting_routes_to_market_worker_for_redirect() -> None:
    # A job-hunting request is a near-miss (design §7.4): it runs the SAME market-intel
    # worker (the responder frames the answer as a redirect), never a listings search.
    decision = await _plan({"intent": "job_hunting", "steps": ["redirect to requirements"]})

    assert decision.intent is Intent.JOB_HUNTING
    assert decision.workers == [WorkerName.MARKET_INTEL]


async def test_off_topic_routes_to_no_workers() -> None:
    decision = await _plan({"intent": "off_topic", "steps": ["decline politely"]})

    assert decision.intent is Intent.OFF_TOPIC
    assert decision.workers == []


async def test_pdp_routes_to_pdp_worker() -> None:
    decision = await _plan({"intent": "pdp", "steps": ["build plan"]})

    assert decision.intent is Intent.PDP
    assert decision.workers == [WorkerName.PDP_RESUME]


async def test_cv_question_routes_to_rag() -> None:
    decision = await _plan({"intent": "cv_question", "steps": ["read cv"]})

    assert decision.intent is Intent.CV_QUESTION
    assert decision.workers == [WorkerName.RAG]


async def test_smalltalk_routes_to_no_workers() -> None:
    decision = await _plan({"intent": "smalltalk", "steps": ["greet back"]})

    assert decision.intent is Intent.SMALLTALK
    assert decision.workers == []


async def test_chat_grounded_routes_to_rag() -> None:
    decision = await _plan({"intent": "chat", "steps": ["answer"], "needs_grounding": True})

    assert decision.intent is Intent.CHAT
    assert decision.workers == [WorkerName.RAG]


async def test_chat_ungrounded_routes_to_no_workers() -> None:
    decision = await _plan({"intent": "chat", "steps": ["answer"], "needs_grounding": False})

    assert decision.workers == []


async def test_chat_defaults_to_ungrounded_when_flag_absent() -> None:
    decision = await _plan({"intent": "chat", "steps": ["answer"]})

    assert decision.workers == []


# --------------------------------------------------------------------------- #
# Steps + budget population
# --------------------------------------------------------------------------- #
async def test_steps_are_carried_through_and_trimmed() -> None:
    decision = await _plan(
        {"intent": "chat", "steps": ["  clarify the goal ", "", "  draft answer"]}
    )

    # blank steps dropped, surrounding whitespace trimmed.
    assert decision.steps == ["clarify the goal", "draft answer"]


async def test_empty_steps_get_a_fallback_step() -> None:
    decision = await _plan({"intent": "market_requirements", "steps": []})

    assert decision.steps  # never empty — a fallback step is synthesised.


async def test_budget_defaults_are_per_intent() -> None:
    smalltalk = await _plan({"intent": "smalltalk", "steps": ["hi"]})
    job = await _plan({"intent": "market_requirements", "steps": ["search"]})

    assert smalltalk.max_iterations == 1
    assert job.max_iterations == 5
    # token_budget is optional (provider default) — left unset by the planner.
    assert job.token_budget is None


# --------------------------------------------------------------------------- #
# Tool-call contract: the planner forces the record_plan function
# --------------------------------------------------------------------------- #
async def test_planner_forces_the_record_plan_tool() -> None:
    completer = FakeCompleter(result=_tool_result({"intent": "chat", "steps": ["answer"]}))

    await Planner(completer).plan(_state("how do I get promoted?"))

    assert completer.last_tools == [PLANNER_TOOL_SCHEMA]
    assert completer.last_tool_choice == {
        "type": "function",
        "function": {"name": PLANNER_TOOL_NAME},
    }
    # the user's message is the final message handed to the model.
    assert completer.last_messages[-1].content == "how do I get promoted?"
    assert completer.last_messages[0].role == "system"


async def test_planner_includes_bounded_history_and_memory() -> None:
    completer = FakeCompleter(result=_tool_result({"intent": "chat", "steps": ["answer"]}))
    history = [ChatMessage(role="user", content=f"m{i}") for i in range(10)]
    state = _state(
        "latest",
        history=history,
        memory={"memories": ["prefers remote roles"]},
    )

    await Planner(completer).plan(state)

    contents = [m.content for m in completer.last_messages]
    # bounded history slice (last 6), the memory note, and the current turn are present.
    assert "m9" in contents
    assert "m0" not in contents
    assert any("prefers remote roles" in (c or "") for c in contents)
    assert contents[-1] == "latest"


# --------------------------------------------------------------------------- #
# Failure path → safe default (never raises out of the node)
# --------------------------------------------------------------------------- #
async def test_router_error_falls_back_to_safe_default() -> None:
    completer = FakeCompleter(error=LLMAllModelsFailedError("all down"))

    decision = await Planner(completer).plan(_state())

    assert decision.intent is Intent.CHAT
    assert decision.workers == []


async def test_missing_tool_call_falls_back() -> None:
    completer = FakeCompleter(result=CompletionResult(content="free text", model="fake"))

    decision = await Planner(completer).plan(_state())

    assert decision.intent is Intent.CHAT
    assert decision.workers == []


async def test_malformed_json_arguments_fall_back() -> None:
    completer = FakeCompleter(result=_tool_result("{not valid json"))

    decision = await Planner(completer).plan(_state())

    assert decision.intent is Intent.CHAT
    assert decision.workers == []


async def test_unknown_intent_falls_back() -> None:
    decision = await _plan({"intent": "make_coffee", "steps": ["brew"]})

    assert decision.intent is Intent.CHAT
    assert decision.workers == []


@pytest.mark.parametrize("bad_steps", [None, 5, 3.14, True, {"a": 1}])
async def test_non_list_steps_do_not_raise_and_get_a_fallback(bad_steps: Any) -> None:
    # ``steps`` is model-controlled: a non-list value (null / number / bool / object)
    # must not raise a TypeError out of the node — it falls back to a synthesised step
    # while the (trusted) intent is still honoured (C1).
    decision = await _plan({"intent": "market_requirements", "steps": bad_steps})

    assert decision.intent is Intent.MARKET_REQUIREMENTS
    assert decision.workers == [WorkerName.MARKET_INTEL]
    assert decision.steps  # synthesised fallback, never empty.


async def test_string_steps_are_not_iterated_char_by_char() -> None:
    # a JSON *string* would otherwise iterate character-by-character into junk steps;
    # the isinstance(list) guard rejects it and synthesises a fallback instead (C3).
    decision = await _plan({"intent": "chat", "steps": "do the thing"})

    assert decision.steps == ["Handle the chat request."]


def test_parse_decision_returns_none_on_non_object_arguments() -> None:
    # a JSON array is valid JSON but not the object shape the schema promises.
    result = _tool_result("[1, 2, 3]")

    assert _parse_decision(result) is None


async def test_node_call_returns_plan_update() -> None:
    completer = FakeCompleter(
        result=_tool_result({"intent": "market_requirements", "steps": ["look up"]})
    )

    update = await Planner(completer)(_state())

    assert set(update) == {"plan"}
    assert update["plan"].workers == [WorkerName.MARKET_INTEL]


# --------------------------------------------------------------------------- #
# Integration: the real compiled graph fans out on the planner's decision
# --------------------------------------------------------------------------- #
async def test_planner_decision_drives_real_graph_fan_out() -> None:
    """A router-backed planner in the real graph runs exactly the routed worker."""
    completer = FakeCompleter(
        result=_tool_result({"intent": "market_requirements", "steps": ["search jobs"]})
    )
    compiled = build_graph(router=completer)

    order: list[str] = []
    async for update in compiled.astream(_state("find me a data job"), stream_mode="updates"):
        order.extend(update.keys())

    assert order == [
        INPUT_GUARDRAIL,
        MEMORY_RECALL,
        PLANNER,
        WorkerName.MARKET_INTEL.value,
        RESPONDER,
        OUTPUT_GUARDRAIL,
        MEMORY_WRITER,
    ]
    # the other workers never ran.
    assert WorkerName.RAG.value not in order
    assert WorkerName.WEB_SEARCH.value not in order


async def test_smalltalk_skips_workers_in_real_graph() -> None:
    completer = FakeCompleter(result=_tool_result({"intent": "smalltalk", "steps": ["greet"]}))
    compiled = build_graph(router=completer)

    order: list[str] = []
    async for update in compiled.astream(_state("hi there"), stream_mode="updates"):
        order.extend(update.keys())

    assert not any(w.value in order for w in WorkerName)
    result = AgentState.model_validate(await compiled.ainvoke(_state("hi there")))
    assert result.plan is not None
    assert result.plan.intent is Intent.SMALLTALK


# --------------------------------------------------------------------------- #
# Topic guardrail (design §7.4): OFF_TOPIC short-circuit + JOB_HUNTING redirect
# --------------------------------------------------------------------------- #
async def test_off_topic_short_circuits_like_a_blocked_turn() -> None:
    """An OFF_TOPIC turn skips every worker AND the responder, returning a canned refusal."""
    completer = FakeCompleter(result=_tool_result({"intent": "off_topic", "steps": ["decline"]}))
    compiled = build_graph(router=completer)

    order: list[str] = []
    async for update in compiled.astream(_state("Is this rash serious?"), stream_mode="updates"):
        order.extend(update.keys())

    # No worker and — crucially — no RESPONDER node ran: straight to the terminal tail.
    assert order == [INPUT_GUARDRAIL, MEMORY_RECALL, PLANNER, OUTPUT_GUARDRAIL, MEMORY_WRITER]
    assert RESPONDER not in order
    assert not any(w.value in order for w in WorkerName)

    result = AgentState.model_validate(await compiled.ainvoke(_state("Is this rash serious?")))
    assert result.plan is not None
    assert result.plan.intent is Intent.OFF_TOPIC
    assert result.response == OFF_TOPIC_REFUSAL
    assert result.finish_reason == "off_topic"


async def test_job_hunting_runs_market_worker_not_a_short_circuit() -> None:
    """A JOB_HUNTING turn runs the market-intel worker (redirect) — not a refusal short-circuit."""
    completer = FakeCompleter(result=_tool_result({"intent": "job_hunting", "steps": ["redirect"]}))
    compiled = build_graph(router=completer)

    order: list[str] = []
    async for update in compiled.astream(
        _state("find me AI architect jobs in Berlin"), stream_mode="updates"
    ):
        order.extend(update.keys())

    # The market-intel worker runs and the responder still composes (frames the redirect).
    assert WorkerName.MARKET_INTEL.value in order
    assert RESPONDER in order
    result = AgentState.model_validate(
        await compiled.ainvoke(_state("find me AI architect jobs in Berlin"))
    )
    assert result.plan is not None
    assert result.plan.intent is Intent.JOB_HUNTING
