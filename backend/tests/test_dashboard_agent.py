"""Unit + integration tests for the Dashboard worker (P8-03, §5.2).

Covers the acceptance criteria:

* the planner routes a dashboard-flavored turn to ``[WorkerName.DASHBOARD]``,
* the node drives a bounded tool-calling loop against a fake ``LLMCompleter`` and its AI writes
  land ``source="ai"`` / ``status="proposed"`` (never silent),
* a **guest** turn fails soft (no tool call, no crash), and
* a graph-level run reaches the responder with a sensible dashboard summary.

The LLM boundary is always a scripted :class:`FakeCompleter`; the dashboard is the real
:class:`~app.services.dashboard.DashboardService` over the in-memory store (no DB).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from app.agents.dashboard_agent import make_dashboard_node
from app.agents.graph import build_graph
from app.agents.planner import Planner
from app.agents.state import AgentState, Intent, PlannerDecision, WorkerName
from app.llm.types import ChatMessage, CompletionResult, FunctionCall, ToolCall, ToolSchema
from app.schemas.dashboard import GoalCreate, TaskCreate
from app.services.dashboard import DashboardService
from app.services.dashboard_store import InMemoryDashboardStore
from app.tools.dashboard import PROPOSE_TASK_TOOL, READ_DASHBOARD_TOOL

USER = "user-1"


class FakeCompleter:
    """Scripted ``LLMCompleter``: replays queued :class:`CompletionResult`s, one per call.

    Records the ``tools``/``tool_choice`` each call saw so a test can assert the node offered the
    dashboard schemas with an ``auto`` choice (the model decides whether to call a tool).
    """

    def __init__(self, results: Sequence[CompletionResult]) -> None:
        self._results = list(results)
        self.calls = 0
        self.last_tools: Sequence[ToolSchema] | None = None
        self.last_tool_choice: Any = None
        self.last_messages: list[ChatMessage] = []

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
        self.last_tools = tools
        self.last_tool_choice = tool_choice
        self.last_messages = list(messages)
        # Replay in order; repeat the last (a no-tool wrap-up) once exhausted.
        return self._results.pop(0) if len(self._results) > 1 else self._results[0]


def _tool_call(name: str, arguments: dict[str, Any], *, call_id: str = "c1") -> CompletionResult:
    return CompletionResult(
        content=None,
        tool_calls=[
            ToolCall(id=call_id, function=FunctionCall(name=name, arguments=json.dumps(arguments)))
        ],
        model="fake",
    )


def _final(content: str = "Done.") -> CompletionResult:
    return CompletionResult(content=content, tool_calls=[], finish_reason="stop", model="fake")


def _service() -> DashboardService:
    return DashboardService(InMemoryDashboardStore())


def _state(user_id: str | None = USER, message: str = "add a task to my plan") -> AgentState:
    return AgentState(session_id="s", user_id=user_id, user_message=message)


# --------------------------------------------------------------------------- #
# Node: propose flow lands source="ai" / proposed
# --------------------------------------------------------------------------- #
async def test_node_proposes_task_source_ai_proposed() -> None:
    service = _service()
    goal = await service.create_goal(USER, GoalCreate(title="Goal"))

    router = FakeCompleter(
        [
            _tool_call(PROPOSE_TASK_TOOL, {"goal_id": goal.id, "title": "Learn Docker"}),
            _final("I proposed a task."),
        ]
    )
    node = make_dashboard_node(service=service, router=router)

    update = await node(_state())
    result = update["worker_results"][WorkerName.DASHBOARD.value]
    assert result.error is None
    assert "proposed" in result.content.lower()
    assert result.data["proposed"], "the proposed task should be recorded in data"

    # The write landed AI-attributed + pending approval (never silent).
    tasks = await service.list_tasks(USER, goal.id)
    assert len(tasks) == 1
    assert tasks[0].source == "ai"
    assert tasks[0].status == "proposed"

    # The node offered the dashboard tools with an ``auto`` choice.
    assert router.last_tool_choice == "auto"
    assert router.last_tools is not None and len(router.last_tools) == 5


async def test_node_read_only_turn_summarizes_read() -> None:
    service = _service()
    router = FakeCompleter([_tool_call(READ_DASHBOARD_TOOL, {}), _final()])
    node = make_dashboard_node(service=service, router=router)

    update = await node(_state(message="what's on my dashboard?"))
    result = update["worker_results"][WorkerName.DASHBOARD.value]
    assert result.error is None
    assert result.data["read"] is True


async def test_node_read_turn_folds_dashboard_data_into_content() -> None:
    """A read turn surfaces the actual goals/tasks in ``content`` (the responder grounds on it)."""
    service = _service()
    goal = await service.create_goal(USER, GoalCreate(title="Become a data engineer"))
    await service.create_task(USER, TaskCreate(goal_id=goal.id, title="Learn SQL"))

    router = FakeCompleter([_tool_call(READ_DASHBOARD_TOOL, {}), _final()])
    node = make_dashboard_node(service=service, router=router)

    update = await node(_state(message="what's on my dashboard?"))
    result = update["worker_results"][WorkerName.DASHBOARD.value]
    assert result.error is None
    assert result.data["read"] is True
    # The dashboard's real contents reach the responder's grounding via WorkerResult.content —
    # not just a "a read happened" line — so the informational turn can actually be answered.
    assert "Become a data engineer" in result.content
    assert "Learn SQL" in result.content


# --------------------------------------------------------------------------- #
# Guest fail-soft + unconfigured node
# --------------------------------------------------------------------------- #
async def test_guest_fails_soft_without_calling_the_model() -> None:
    service = _service()
    router = FakeCompleter([_final()])
    node = make_dashboard_node(service=service, router=router)

    update = await node(_state(user_id=None))
    result = update["worker_results"][WorkerName.DASHBOARD.value]
    assert result.error is not None
    assert "account" in result.error.lower()
    assert "sign in" in (result.content or "").lower()
    # The model was never called for a guest, and nothing was written.
    assert router.calls == 0


async def test_unconfigured_node_fails_soft() -> None:
    node = make_dashboard_node()  # no service / router
    update = await node(_state())
    result = update["worker_results"][WorkerName.DASHBOARD.value]
    assert result.error == "dashboard worker not configured"


async def test_node_never_calls_a_write_tool_for_a_guest_even_if_service_present() -> None:
    """A guest reaching the node writes nothing to the store (defence in depth)."""
    service = _service()
    node = make_dashboard_node(service=service, router=FakeCompleter([_final()]))
    await node(_state(user_id=None))
    # No user_id was ever bound to a write.
    assert await service.list_goals(USER) == []


# --------------------------------------------------------------------------- #
# Planner routing: a dashboard-flavored turn routes to [WorkerName.DASHBOARD]
# --------------------------------------------------------------------------- #
async def test_planner_routes_dashboard_turn_to_dashboard_worker() -> None:
    planner_completer = FakeCompleter(
        [
            CompletionResult(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="c1",
                        function=FunctionCall(
                            name="record_plan",
                            arguments=json.dumps(
                                {"intent": "dashboard", "steps": ["Add the tasks to the plan."]}
                            ),
                        ),
                    )
                ],
                model="fake",
            )
        ]
    )
    decision = await Planner(planner_completer).plan(_state(message="add these 5 tasks to my plan"))
    assert decision.intent is Intent.DASHBOARD
    assert decision.workers == [WorkerName.DASHBOARD]


# --------------------------------------------------------------------------- #
# Graph-level integration: a dashboard turn reaches the responder with a summary
# --------------------------------------------------------------------------- #
def _planner_selecting_dashboard() -> Any:
    def planner(state: AgentState) -> dict[str, Any]:
        return {"plan": PlannerDecision(intent=Intent.DASHBOARD, workers=[WorkerName.DASHBOARD])}

    return planner


async def test_graph_dashboard_turn_reaches_responder_with_summary() -> None:
    service = _service()
    goal = await service.create_goal(USER, GoalCreate(title="Become a data engineer"))
    router = FakeCompleter(
        [
            _tool_call(PROPOSE_TASK_TOOL, {"goal_id": goal.id, "title": "Learn SQL"}),
            _final(),
        ]
    )
    compiled = build_graph(
        planner=_planner_selecting_dashboard(),
        dashboard_service=service,
        router=router,
    )
    final = await compiled.ainvoke(_state(user_id=USER))
    state = AgentState.model_validate(final)

    dashboard_result = state.worker_results[WorkerName.DASHBOARD.value]
    assert "proposed" in dashboard_result.content.lower()
    # The deterministic default responder echoes worker content → the summary reaches the answer.
    assert state.response is not None and "proposed" in state.response.lower()

    tasks = await service.list_tasks(USER, goal.id)
    assert tasks[0].status == "proposed" and tasks[0].source == "ai"
