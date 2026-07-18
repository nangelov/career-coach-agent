"""Unit tests for the native dashboard tools (P8-03, §5.2).

Driven entirely against the in-memory :class:`~app.services.dashboard_store.InMemoryDashboardStore`
+ the real :class:`~app.services.dashboard.DashboardService` (no DB). The security-critical
property is asserted directly: every propose tool writes ``source="ai"`` (which the service
resolves to ``status="proposed"``), so an AI write is never applied silently.
"""

from __future__ import annotations

import json

from app.services.dashboard import DashboardService
from app.services.dashboard_store import InMemoryDashboardStore
from app.tools.base import ToolRegistry
from app.tools.dashboard import (
    LOG_PROGRESS_TOOL,
    PROPOSE_GOAL_TOOL,
    PROPOSE_MILESTONE_TOOL,
    PROPOSE_TASK_TOOL,
    READ_DASHBOARD_TOOL,
    build_dashboard_tools,
)

USER = "user-1"


def _service() -> DashboardService:
    return DashboardService(InMemoryDashboardStore())


def _tools(service: DashboardService, user_id: str = USER) -> dict[str, object]:
    return {tool.name: tool for tool in build_dashboard_tools(user_id, service)}


def _payload(result: object) -> dict:
    return json.loads(result.content)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Schemas + registry wiring
# --------------------------------------------------------------------------- #
def test_all_five_tools_have_openai_shaped_schemas() -> None:
    tools = build_dashboard_tools(USER, _service())
    names = {t.name for t in tools}
    assert names == {
        READ_DASHBOARD_TOOL,
        PROPOSE_GOAL_TOOL,
        PROPOSE_MILESTONE_TOOL,
        PROPOSE_TASK_TOOL,
        LOG_PROGRESS_TOOL,
    }
    for tool in tools:
        schema = tool.schema
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] == tool.name
        assert fn["parameters"]["type"] == "object"
        # No propose tool exposes a ``status`` argument — attribution is server-resolved.
        assert "status" not in fn["parameters"]["properties"]


async def test_tools_register_into_a_registry() -> None:
    registry = ToolRegistry()
    for tool in build_dashboard_tools(USER, _service()):
        registry.register(tool)
    assert set(registry.names()) == {
        READ_DASHBOARD_TOOL,
        PROPOSE_GOAL_TOOL,
        PROPOSE_MILESTONE_TOOL,
        PROPOSE_TASK_TOOL,
        LOG_PROGRESS_TOOL,
    }


# --------------------------------------------------------------------------- #
# Propose tools write source="ai" → status="proposed"
# --------------------------------------------------------------------------- #
async def test_propose_goal_writes_ai_proposed() -> None:
    service = _service()
    tools = _tools(service)

    result = await tools[PROPOSE_GOAL_TOOL].run({"title": "Become a data engineer"})
    payload = _payload(result)
    assert payload["proposed"] == "goal"
    assert payload["status"] == "proposed"

    # The persisted row is attributed to the AI and pending approval.
    goals = await service.list_goals(USER)
    assert len(goals) == 1
    assert goals[0].source == "ai"
    assert goals[0].status == "proposed"


async def test_propose_milestone_and_task_write_ai_proposed() -> None:
    service = _service()
    tools = _tools(service)

    goal_id = _payload(await tools[PROPOSE_GOAL_TOOL].run({"title": "Goal"}))["id"]

    m = _payload(
        await tools[PROPOSE_MILESTONE_TOOL].run({"goal_id": goal_id, "title": "Milestone"})
    )
    assert m["proposed"] == "milestone" and m["status"] == "proposed"

    t = _payload(await tools[PROPOSE_TASK_TOOL].run({"goal_id": goal_id, "title": "Task"}))
    assert t["proposed"] == "task" and t["status"] == "proposed"

    milestones = await service.list_milestones(USER, goal_id)
    tasks = await service.list_tasks(USER, goal_id)
    assert milestones is not None and milestones[0].source == "ai"
    assert tasks[0].source == "ai" and tasks[0].status == "proposed"


async def test_log_progress_writes_ai_entry() -> None:
    service = _service()
    tools = _tools(service)

    result = await tools[LOG_PROGRESS_TOOL].run({"note": "Finished the SQL course."})
    assert _payload(result)["logged"] == "progress"

    entries = await service.list_progress(USER, limit=10, offset=0)
    assert len(entries) == 1
    assert entries[0].source == "ai"
    assert entries[0].note == "Finished the SQL course."


# --------------------------------------------------------------------------- #
# Read tool
# --------------------------------------------------------------------------- #
async def test_read_dashboard_returns_summary() -> None:
    service = _service()
    tools = _tools(service)
    await tools[PROPOSE_GOAL_TOOL].run({"title": "Goal A"})

    payload = _payload(await tools[READ_DASHBOARD_TOOL].run({}))
    assert "goals" in payload and "progress" in payload
    assert len(payload["goals"]) == 1
    assert payload["goals"][0]["title"] == "Goal A"


# --------------------------------------------------------------------------- #
# Graceful failures (never raise — return a ToolResult.error)
# --------------------------------------------------------------------------- #
async def test_propose_milestone_under_missing_goal_is_graceful_error() -> None:
    tools = _tools(_service())
    result = await tools[PROPOSE_MILESTONE_TOOL].run({"goal_id": "nope", "title": "M"})
    assert result.is_error  # type: ignore[attr-defined]
    assert "goal" in _payload(result)["error"].lower()


async def test_propose_task_under_missing_goal_is_graceful_error() -> None:
    tools = _tools(_service())
    result = await tools[PROPOSE_TASK_TOOL].run({"goal_id": "nope", "title": "T"})
    assert result.is_error  # type: ignore[attr-defined]


async def test_propose_goal_missing_title_is_graceful_error() -> None:
    tools = _tools(_service())
    result = await tools[PROPOSE_GOAL_TOOL].run({})
    assert result.is_error  # type: ignore[attr-defined]


async def test_tool_is_scoped_to_bound_user() -> None:
    """A tool bound to one user never writes to (or reads) another user's dashboard."""
    service = _service()
    # user-1 proposes a goal via their bound tool.
    _tools(service, "user-1")
    await _tools(service, "user-1")[PROPOSE_GOAL_TOOL].run({"title": "Owned"})

    # user-2's read tool sees an empty dashboard (scoping enforced by the bound user_id).
    payload = _payload(await _tools(service, "user-2")[READ_DASHBOARD_TOOL].run({}))
    assert payload["goals"] == []
