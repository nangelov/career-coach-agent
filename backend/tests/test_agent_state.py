"""Unit tests for the shared LangGraph agent state (P4-01, design §3).

Covers the four things the task's acceptance criteria call out:

* construction (minimal + full),
* reducer/merge behaviour for **concurrent** worker writes (the main technical risk —
  parallel workers must not clobber each other's slice),
* a JSON serialization round trip (state crosses the Redis / Celery boundary), and
* the validation the model enforces.

The reducer test drives a real :class:`~langgraph.graph.StateGraph` fan-out (two workers
from ``START`` writing at the same superstep) so we prove the ``Annotated`` reducers work
under LangGraph's actual concurrent-update path, not just as bare functions.
"""

from __future__ import annotations

import operator

import pytest
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.agents.state import (
    AgentState,
    Citation,
    GuardrailStage,
    Intent,
    MemoryContext,
    PlannerDecision,
    SafetyVerdict,
    WorkerName,
    WorkerResult,
    merge_worker_results,
)
from app.llm.types import ChatMessage


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #
def test_minimal_construction_defaults_every_slice() -> None:
    state = AgentState(session_id="s-1", user_message="hi")

    assert state.session_id == "s-1"
    assert state.user_message == "hi"
    # guest-by-default identity (design §4: guests are the un-authenticated baseline).
    assert state.user_id is None
    assert state.role == "guest"
    # every downstream slice starts empty / unset.
    assert state.message_id is None
    assert state.history == []
    assert state.plan is None
    assert state.worker_results == {}
    assert state.citations == []
    assert state.response is None
    assert state.input_safety is None
    assert state.output_safety is None
    # memory recall slot is present but empty until P9 fills it.
    assert isinstance(state.memory, MemoryContext)
    assert state.memory.preferences == {}
    assert state.memory.memories == []


def test_full_construction_with_all_slices() -> None:
    state = AgentState(
        session_id="s-2",
        user_id="u-9",
        role="user",
        user_message="find me a job",
        message_id="m-1",
        history=[ChatMessage(role="user", content="earlier turn")],
        memory=MemoryContext(preferences={"tone": "concise"}, memories=["prefers remote"]),
        plan=PlannerDecision(
            intent=Intent.JOB_SEARCH,
            steps=["search", "score"],
            workers=[WorkerName.JOB_SEARCH, WorkerName.RAG],
            token_budget=2000,
        ),
        input_safety=SafetyVerdict(stage=GuardrailStage.INPUT, allowed=True),
    )

    assert state.role == "user"
    assert state.plan is not None
    assert state.plan.intent is Intent.JOB_SEARCH
    assert state.plan.workers == [WorkerName.JOB_SEARCH, WorkerName.RAG]
    # history is LLM-ready — each message renders to the provider wire shape.
    assert state.history[0].to_openai() == {"role": "user", "content": "earlier turn"}


def test_default_slices_are_not_shared_between_instances() -> None:
    """Mutable defaults must be per-instance (default_factory), not class-level."""
    a = AgentState(session_id="a", user_message="x")
    b = AgentState(session_id="b", user_message="y")

    a.citations.append(Citation(title="only-a"))
    a.worker_results["rag"] = WorkerResult(worker=WorkerName.RAG)

    assert b.citations == []
    assert b.worker_results == {}


# --------------------------------------------------------------------------- #
# Reducer / merge behaviour (the main technical risk)
# --------------------------------------------------------------------------- #
def test_merge_worker_results_is_key_wise() -> None:
    left = {"rag": WorkerResult(worker=WorkerName.RAG, content="a")}
    right = {"web_search": WorkerResult(worker=WorkerName.WEB_SEARCH, content="b")}

    merged = merge_worker_results(left, right)

    assert set(merged) == {"rag", "web_search"}
    assert merged["rag"].content == "a"
    assert merged["web_search"].content == "b"


def test_citations_reducer_is_list_concatenation() -> None:
    # operator.add is the declared reducer; assert the semantics we rely on.
    assert operator.add([Citation(title="a")], [Citation(title="b")]) == [
        Citation(title="a"),
        Citation(title="b"),
    ]


def test_parallel_workers_accumulate_without_clobbering() -> None:
    """Two workers fan out from START and write in the same superstep.

    Proves the ``Annotated`` reducers on ``worker_results`` and ``citations`` fold both
    concurrent updates into the state instead of one overwriting the other.
    """

    def rag_worker(state: AgentState) -> dict[str, object]:
        return {
            "worker_results": {
                WorkerName.RAG: WorkerResult(worker=WorkerName.RAG, content="rag-out")
            },
            "citations": [Citation(title="kb-doc", worker=WorkerName.RAG)],
        }

    def web_worker(state: AgentState) -> dict[str, object]:
        return {
            "worker_results": {
                WorkerName.WEB_SEARCH: WorkerResult(worker=WorkerName.WEB_SEARCH, content="web-out")
            },
            "citations": [Citation(url="https://x", worker=WorkerName.WEB_SEARCH)],
        }

    graph = StateGraph(AgentState)
    graph.add_node("rag", rag_worker)
    graph.add_node("web", web_worker)
    graph.add_edge(START, "rag")
    graph.add_edge(START, "web")
    graph.add_edge("rag", END)
    graph.add_edge("web", END)
    compiled = graph.compile()

    result = AgentState.model_validate(
        compiled.invoke(AgentState(session_id="s", user_message="hi"))
    )

    # both workers' result slices survived the concurrent fan-in.
    assert set(result.worker_results) == {WorkerName.RAG, WorkerName.WEB_SEARCH}
    assert result.worker_results[WorkerName.RAG].content == "rag-out"
    assert result.worker_results[WorkerName.WEB_SEARCH].content == "web-out"
    # both citations accumulated (order not guaranteed under concurrency).
    assert {c.worker for c in result.citations} == {
        WorkerName.RAG,
        WorkerName.WEB_SEARCH,
    }
    assert len(result.citations) == 2


# --------------------------------------------------------------------------- #
# Serialization round trip (Redis / Celery boundary)
# --------------------------------------------------------------------------- #
def test_json_round_trip_preserves_full_state() -> None:
    state = AgentState(
        session_id="s-3",
        user_id="u-1",
        role="user",
        user_message="hello",
        message_id="m-42",
        history=[ChatMessage(role="assistant", content="prior", message_id="m-41")],
        memory=MemoryContext(preferences={"language": "en"}, memories=["likes bullet points"]),
        plan=PlannerDecision(intent=Intent.PDP, workers=[WorkerName.PDP_RESUME]),
        worker_results={
            "pdp_resume": WorkerResult(
                worker=WorkerName.PDP_RESUME,
                content="draft",
                citations=[Citation(source_id="chunk-1")],
            )
        },
        citations=[Citation(title="cited", worker=WorkerName.PDP_RESUME)],
        response="here is your plan",
        finish_reason="stop",
        input_safety=SafetyVerdict(stage=GuardrailStage.INPUT),
        output_safety=SafetyVerdict(
            stage=GuardrailStage.OUTPUT, allowed=False, categories=["leak"], reason="pii"
        ),
    )

    restored = AgentState.model_validate_json(state.model_dump_json())

    assert restored == state
    # enums survive as their typed selves, not raw strings.
    assert restored.plan is not None
    assert restored.plan.intent is Intent.PDP
    assert restored.output_safety is not None
    assert restored.output_safety.stage is GuardrailStage.OUTPUT
    assert restored.output_safety.allowed is False


def test_enum_values_serialize_to_plain_strings() -> None:
    state = AgentState(
        session_id="s",
        user_message="x",
        plan=PlannerDecision(intent=Intent.JOB_SEARCH, workers=[WorkerName.WEB_SEARCH]),
    )

    dumped = state.model_dump(mode="json")

    assert dumped["plan"]["intent"] == "job_search"
    assert dumped["plan"]["workers"] == ["web_search"]


# --------------------------------------------------------------------------- #
# Validation the model enforces
# --------------------------------------------------------------------------- #
def test_session_id_is_required_and_bounded() -> None:
    with pytest.raises(ValidationError):
        AgentState(user_message="x")  # type: ignore[call-arg]

    with pytest.raises(ValidationError):
        AgentState(session_id="", user_message="x")

    with pytest.raises(ValidationError):
        AgentState(session_id="s" * 65, user_message="x")


def test_planner_budget_bounds_are_enforced() -> None:
    with pytest.raises(ValidationError):
        PlannerDecision(intent=Intent.CHAT, max_iterations=0)

    with pytest.raises(ValidationError):
        PlannerDecision(intent=Intent.CHAT, token_budget=0)


def test_invalid_intent_and_worker_rejected() -> None:
    with pytest.raises(ValidationError):
        PlannerDecision(intent="not-a-real-intent")

    with pytest.raises(ValidationError):
        WorkerResult(worker="not-a-worker")
