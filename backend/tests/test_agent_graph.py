"""Integration tests for the multi-agent LangGraph wiring (P4-02, design §3).

These tests exercise the **real compiled graph**, not the individual stub bodies, and
assert the four things the task's acceptance criteria call out:

* the turn flows through every node in the design §3 order
  (input guardrail → recall → planner → workers → responder → output guardrail →
  memory writer),
* conditional fan-out dispatches **only** the workers the planner selected,
* parallel workers fan in without clobbering each other's ``worker_results`` /
  ``citations`` (the P4-01 reducers exercised through an actual graph run), and
* the guardrail/memory hooks are wired in the right positions with the right shape.

The planner override on :func:`build_graph` is used purely as a test seam to drive
different routings through the *real* graph until P4-03 lands the real planner.

The ``rag`` worker is real as of P4-04 (an ``async`` node), so any turn that routes through
it is exercised via LangGraph's **async** runtime (``astream`` / ``ainvoke``) — a sync
``invoke`` on that path would raise "No synchronous function provided". Turns that do not
route RAG (e.g. the module ``graph`` with the no-op default planner) still run synchronously.
The fan-in tests inject a fake embedder + scripted DB (``tests.fakes``) so the real ``rag``
node contributes a citation like any other worker.
"""

from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from app.agents.graph import (
    INPUT_GUARDRAIL,
    MEMORY_RECALL,
    MEMORY_WRITER,
    OUTPUT_GUARDRAIL,
    PLANNER,
    RESPONDER,
    NodeUpdate,
    PlannerNode,
    build_graph,
    graph,
    route_after_planner,
    run_graph,
)
from app.agents.state import (
    AgentState,
    GuardrailStage,
    Intent,
    PlannerDecision,
    WorkerName,
)
from tests.fakes import (
    FakeEmbeddingClient,
    FakeSearchTool,
    fake_crawl_client,
    rag_db_one_hit,
    web_result,
)


def _planner_selecting(*workers: WorkerName) -> PlannerNode:
    """A stub planner node that routes to exactly ``workers`` (test seam for routing)."""

    def planner(state: AgentState) -> NodeUpdate:
        return {"plan": PlannerDecision(intent=Intent.CHAT, workers=list(workers))}

    return planner


async def _node_order(compiled: CompiledStateGraph[AgentState], state: AgentState) -> list[str]:
    """The order nodes actually executed, from LangGraph's per-node update stream.

    Uses the **async** stream because the real ``rag`` worker (P4-04) is an async node —
    the graph is driven the same way it is in production (``run_graph`` → ``ainvoke``).
    """
    order: list[str] = []
    async for update in compiled.astream(state, stream_mode="updates"):
        order.extend(update.keys())
    return order


# --------------------------------------------------------------------------- #
# Node sequence / ordering (design §3 diagram)
# --------------------------------------------------------------------------- #
async def test_turn_flows_through_every_node_in_design_order() -> None:
    """Single-worker turn visits the full design §3 pipeline in order."""
    compiled = build_graph(planner=_planner_selecting(WorkerName.RAG))

    order = await _node_order(compiled, AgentState(session_id="s", user_message="hi"))

    assert order == [
        INPUT_GUARDRAIL,
        MEMORY_RECALL,
        PLANNER,
        WorkerName.RAG.value,
        RESPONDER,
        OUTPUT_GUARDRAIL,
        MEMORY_WRITER,
    ]


async def test_guardrails_bracket_the_pipeline() -> None:
    """Input guardrail runs before planner; output guardrail after responder."""
    compiled = build_graph(planner=_planner_selecting(WorkerName.RAG))

    order = await _node_order(compiled, AgentState(session_id="s", user_message="hi"))

    assert order.index(INPUT_GUARDRAIL) < order.index(PLANNER)
    assert order.index(RESPONDER) < order.index(OUTPUT_GUARDRAIL)
    # memory writer is terminal (post-response, last node before END).
    assert order[-1] == MEMORY_WRITER


# --------------------------------------------------------------------------- #
# Conditional fan-out (only planner-selected workers run)
# --------------------------------------------------------------------------- #
async def test_only_selected_workers_are_dispatched() -> None:
    """Planner selecting two of four workers runs exactly those two."""
    compiled = build_graph(planner=_planner_selecting(WorkerName.RAG, WorkerName.JOB_SEARCH))

    order = await _node_order(compiled, AgentState(session_id="s", user_message="find work"))

    assert WorkerName.RAG.value in order
    assert WorkerName.JOB_SEARCH.value in order
    # the unselected workers never execute.
    assert WorkerName.WEB_SEARCH.value not in order
    assert WorkerName.PDP_RESUME.value not in order


async def test_no_workers_routes_straight_to_responder() -> None:
    """When the planner selects no workers the turn still completes via the responder."""
    compiled = build_graph(planner=_planner_selecting())

    order = await _node_order(compiled, AgentState(session_id="s", user_message="hello"))

    assert not any(order.count(w.value) for w in WorkerName)
    assert order == [
        INPUT_GUARDRAIL,
        MEMORY_RECALL,
        PLANNER,
        RESPONDER,
        OUTPUT_GUARDRAIL,
        MEMORY_WRITER,
    ]


def test_route_after_planner_dedupes_workers() -> None:
    """A worker listed twice is dispatched once (no duplicate node runs)."""
    state = AgentState(
        session_id="s",
        user_message="x",
        plan=PlannerDecision(intent=Intent.CHAT, workers=[WorkerName.RAG, WorkerName.RAG]),
    )

    sends = route_after_planner(state)

    assert [s.node for s in sends] == [WorkerName.RAG.value]


def test_route_after_planner_falls_back_to_responder() -> None:
    state = AgentState(session_id="s", user_message="x")  # no plan set

    sends = route_after_planner(state)

    assert [s.node for s in sends] == [RESPONDER]


# --------------------------------------------------------------------------- #
# Parallel fan-in (P4-01 reducers through a real graph run)
# --------------------------------------------------------------------------- #
async def test_parallel_workers_fan_in_without_clobbering() -> None:
    """All four workers run concurrently; every slice survives the fan-in."""
    db, _doc_id, _chunk_id = rag_db_one_hit()
    # Inject a fake web search tool + mock crawl transport so the real web_search worker
    # (P4-05) contributes one citation like any other worker — no real network.
    compiled = build_graph(
        planner=_planner_selecting(
            WorkerName.RAG,
            WorkerName.WEB_SEARCH,
            WorkerName.JOB_SEARCH,
            WorkerName.PDP_RESUME,
        ),
        embedder=FakeEmbeddingClient(),
        db=db,
        search_tool=FakeSearchTool([web_result()]),
        http_client=fake_crawl_client(),
    )

    result = AgentState.model_validate(
        await compiled.ainvoke(AgentState(session_id="s", user_message="everything"))
    )

    # every dispatched worker owns a distinct key — none overwrote another.
    assert set(result.worker_results) == {w.value for w in WorkerName}
    # citations list-concatenated: one per worker (RAG's real hit included), all present.
    assert len(result.citations) == 4
    assert {c.worker for c in result.citations} == set(WorkerName)


async def test_responder_merges_all_worker_outputs() -> None:
    """Responder sees the fully-merged worker_results (fan-in feeds it)."""
    db, _doc_id, _chunk_id = rag_db_one_hit()
    compiled = build_graph(
        planner=_planner_selecting(WorkerName.RAG, WorkerName.WEB_SEARCH),
        embedder=FakeEmbeddingClient(),
        db=db,
        search_tool=FakeSearchTool([web_result(title="WebFinding")]),
        http_client=fake_crawl_client(),
    )

    result = AgentState.model_validate(
        await compiled.ainvoke(AgentState(session_id="s", user_message="hi"))
    )

    assert result.response is not None
    # RAG's grounded excerpt ("rag-source") and the web worker's grounded content both merged
    # in — the responder joins every dispatched worker's real content slice.
    assert "rag-source" in result.response
    assert "WebFinding" in result.response
    assert result.finish_reason == "stop"
    assert result.message_id is not None


# --------------------------------------------------------------------------- #
# Guardrail + entrypoint contract
# --------------------------------------------------------------------------- #
def test_guardrail_stubs_populate_allowed_verdicts() -> None:
    result = AgentState.model_validate(graph.invoke(AgentState(session_id="s", user_message="hi")))

    assert result.input_safety is not None
    assert result.input_safety.stage is GuardrailStage.INPUT
    assert result.input_safety.allowed is True
    assert result.output_safety is not None
    assert result.output_safety.stage is GuardrailStage.OUTPUT
    assert result.output_safety.allowed is True


def test_module_graph_is_compiled_once() -> None:
    """The production graph is a module-level singleton, not rebuilt per import use."""
    import importlib

    graph_module = importlib.import_module("app.agents.graph")
    # re-importing yields the same already-compiled object (compiled once at import).
    assert graph_module.graph is graph


async def test_run_graph_returns_validated_state() -> None:
    result = await run_graph(AgentState(session_id="s", user_message="hi"))

    assert isinstance(result, AgentState)
    assert result.response is not None
    assert result.output_safety is not None
