"""Native dashboard tools — read the living PDP + **propose** changes (P8-03, §5.2).

The LLM-callable surface over the P8-02 :class:`~app.services.dashboard.DashboardService`
that lets the assistant, mid-conversation, look at the user's dashboard and *propose*
goals / milestones / tasks / progress notes ("add these 5 tasks to my plan"). Follows the
canonical ``app/tools/base.py`` :class:`Tool` pattern (JSON schema in, structured
:class:`ToolResult` out) the planner / market extractor already use — no ReAct parsing.

**Never silent (task acceptance, §5.2).** Every *propose* tool calls the service with
``source="ai"`` only (which the service resolves to ``status="proposed"`` — the
pending-approval state). No tool passes ``status`` directly, so an AI write can never land
as a normal, already-active row: the user approves it later via the existing
``PATCH .../goals|milestones|tasks`` endpoints. There is no "approve" tool here.

**Per-turn construction (task §"constructed per turn").** :meth:`Tool.run` only sees the
parsed arguments — it has no per-request context — so these tools close over the caller's
``user_id`` and the shared service. :func:`build_dashboard_tools` builds a fresh bundle
bound to one ``user_id`` for each turn; the dashboard node (P8-03) registers them into a
per-turn :class:`~app.tools.base.ToolRegistry`. A **guest** (``user_id is None``) never
reaches these tools — the node fails soft before building them (§5.2: dashboard requires an
account) — so ``user_id`` here is always a real account id.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.schemas.dashboard import (
    GoalCreate,
    MilestoneCreate,
    ProgressEntryCreate,
    TaskCreate,
)
from app.services.dashboard import DashboardService
from app.tools.base import Tool, ToolResult, ToolSchema

__all__ = [
    "LOG_PROGRESS_TOOL",
    "PROPOSE_GOAL_TOOL",
    "PROPOSE_MILESTONE_TOOL",
    "PROPOSE_TASK_TOOL",
    "READ_DASHBOARD_TOOL",
    "build_dashboard_tools",
]

#: Attribution every propose tool writes — the service resolves this to ``status="proposed"``
#: (pending approval, §5.2). Tools never pass ``status`` directly (kept out of the schema too).
_AI_SOURCE = "ai"

# Tool names (single source of truth; also the ``schema.function.name``).
READ_DASHBOARD_TOOL = "read_dashboard"
PROPOSE_GOAL_TOOL = "propose_goal"
PROPOSE_MILESTONE_TOOL = "propose_milestone"
PROPOSE_TASK_TOOL = "propose_task"
LOG_PROGRESS_TOOL = "log_progress"


def build_dashboard_tools(user_id: str, service: DashboardService) -> list[Tool]:
    """Build the per-turn dashboard tool bundle bound to ``user_id`` (task §"constructed per turn").

    Every tool closes over the caller's ``user_id`` and the shared service, so the model never
    supplies (and can never spoof) whose dashboard is read/written. Registered into a fresh
    per-turn :class:`~app.tools.base.ToolRegistry` by the dashboard node.
    """
    return [
        ReadDashboardTool(user_id, service),
        ProposeGoalTool(user_id, service),
        ProposeMilestoneTool(user_id, service),
        ProposeTaskTool(user_id, service),
        LogProgressTool(user_id, service),
    ]


class _DashboardTool(Tool):
    """Base for the per-turn dashboard tools — binds the caller's ``user_id`` + the service."""

    def __init__(self, user_id: str, service: DashboardService) -> None:
        self._user_id = user_id
        self._service = service


class ReadDashboardTool(_DashboardTool):
    """Read the caller's dashboard: goals (nested milestones/tasks) + progress rollup (§5.2)."""

    _SCHEMA: ToolSchema = {
        "type": "function",
        "function": {
            "name": READ_DASHBOARD_TOOL,
            "description": (
                "Read the current user's development-plan dashboard: their goals with nested "
                "milestones and tasks, progress percentages, and a recent-activity/streak "
                "summary. Call this first to see what already exists before proposing changes."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }

    @property
    def name(self) -> str:
        return READ_DASHBOARD_TOOL

    @property
    def schema(self) -> ToolSchema:
        return self._SCHEMA

    async def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        summary = await self._service.get_summary(self._user_id)
        return ToolResult.ok(summary.model_dump(mode="json"))


class ProposeGoalTool(_DashboardTool):
    """Propose a new career goal (created ``source="ai"`` → ``status="proposed"``, §5.2)."""

    _SCHEMA: ToolSchema = {
        "type": "function",
        "function": {
            "name": PROPOSE_GOAL_TOOL,
            "description": (
                "Propose a new career goal for the user's development plan. The goal is created "
                "as a PROPOSED suggestion the user must approve on their dashboard — it is never "
                "applied silently."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short title of the goal (e.g. 'Become a data engineer').",
                    },
                    "target_role": {
                        "type": "string",
                        "description": "Optional target role/title this goal aims at.",
                    },
                    "target_date": {
                        "type": "string",
                        "description": "Optional ISO date (YYYY-MM-DD) the plan aims for.",
                    },
                },
                "required": ["title"],
                "additionalProperties": False,
            },
        },
    }

    @property
    def name(self) -> str:
        return PROPOSE_GOAL_TOOL

    @property
    def schema(self) -> ToolSchema:
        return self._SCHEMA

    async def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            data = GoalCreate.model_validate(dict(arguments))
        except ValidationError as exc:
            return ToolResult.error(f"Invalid goal: {_first_error(exc)}")
        goal = await self._service.create_goal(self._user_id, data, source=_AI_SOURCE)
        return ToolResult.ok(
            {"proposed": "goal", "id": goal.id, "title": goal.title, "status": goal.status}
        )


class ProposeMilestoneTool(_DashboardTool):
    """Propose a milestone under one of the caller's goals (``source="ai"`` → ``proposed``)."""

    _SCHEMA: ToolSchema = {
        "type": "function",
        "function": {
            "name": PROPOSE_MILESTONE_TOOL,
            "description": (
                "Propose a milestone (a checkpoint) under one of the user's existing goals. "
                "Created as a PROPOSED suggestion the user must approve — never applied silently. "
                "Use read_dashboard first to get the goal_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {
                        "type": "string",
                        "description": "Id of the user's goal this milestone belongs under.",
                    },
                    "title": {"type": "string", "description": "Short title of the milestone."},
                    "due_date": {
                        "type": "string",
                        "description": "Optional ISO date (YYYY-MM-DD) the milestone is due.",
                    },
                },
                "required": ["goal_id", "title"],
                "additionalProperties": False,
            },
        },
    }

    @property
    def name(self) -> str:
        return PROPOSE_MILESTONE_TOOL

    @property
    def schema(self) -> ToolSchema:
        return self._SCHEMA

    async def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        args = dict(arguments)
        # ``goal_id`` addresses the parent goal (a service arg), not a ``MilestoneCreate`` field —
        # drop it before validating so this does not rely on pydantic's ``extra="ignore"`` default.
        goal_id = args.pop("goal_id", None)
        if not isinstance(goal_id, str) or not goal_id.strip():
            return ToolResult.error("Invalid milestone: 'goal_id' is required.")
        try:
            data = MilestoneCreate.model_validate(args)
        except ValidationError as exc:
            return ToolResult.error(f"Invalid milestone: {_first_error(exc)}")
        milestone = await self._service.create_milestone(
            self._user_id, goal_id, data, source=_AI_SOURCE
        )
        if milestone is None:
            return ToolResult.error(f"No goal {goal_id!r} for this user to add a milestone to.")
        return ToolResult.ok(
            {
                "proposed": "milestone",
                "id": milestone.id,
                "goal_id": milestone.goal_id,
                "title": milestone.title,
                "status": milestone.status,
            }
        )


class ProposeTaskTool(_DashboardTool):
    """Propose a task under one of the caller's goals (``source="ai"`` → ``proposed``)."""

    _SCHEMA: ToolSchema = {
        "type": "function",
        "function": {
            "name": PROPOSE_TASK_TOOL,
            "description": (
                "Propose an actionable task under one of the user's existing goals (optionally "
                "under a milestone of that goal). Created as a PROPOSED suggestion the user must "
                "approve — never applied silently. Use read_dashboard first to get the goal_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {
                        "type": "string",
                        "description": "Id of the user's goal this task belongs under.",
                    },
                    "milestone_id": {
                        "type": "string",
                        "description": "Optional id of a milestone (same goal) to attach to.",
                    },
                    "title": {"type": "string", "description": "Short title of the task."},
                    "description": {
                        "type": "string",
                        "description": "Optional longer description of what the task involves.",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "Optional ISO date (YYYY-MM-DD) the task is due.",
                    },
                },
                "required": ["goal_id", "title"],
                "additionalProperties": False,
            },
        },
    }

    @property
    def name(self) -> str:
        return PROPOSE_TASK_TOOL

    @property
    def schema(self) -> ToolSchema:
        return self._SCHEMA

    async def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            data = TaskCreate.model_validate(dict(arguments))
        except ValidationError as exc:
            return ToolResult.error(f"Invalid task: {_first_error(exc)}")
        task = await self._service.create_task(self._user_id, data, source=_AI_SOURCE)
        if task is None:
            return ToolResult.error(
                f"No goal {data.goal_id!r} (or milestone) for this user to add a task to."
            )
        return ToolResult.ok(
            {
                "proposed": "task",
                "id": task.id,
                "goal_id": task.goal_id,
                "title": task.title,
                "status": task.status,
            }
        )


class LogProgressTool(_DashboardTool):
    """Log a progress/check-in note (append-only; created ``source="ai"``, §5.2)."""

    _SCHEMA: ToolSchema = {
        "type": "function",
        "function": {
            "name": LOG_PROGRESS_TOOL,
            "description": (
                "Log a progress/check-in note to the user's plan, optionally referencing one of "
                "their goals and/or tasks (e.g. 'finished the SQL course today'). Appended as an "
                "AI-attributed entry."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "The progress note text."},
                    "goal_id": {
                        "type": "string",
                        "description": "Optional id of a goal this progress relates to.",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Optional id of a task this progress relates to.",
                    },
                },
                "required": ["note"],
                "additionalProperties": False,
            },
        },
    }

    @property
    def name(self) -> str:
        return LOG_PROGRESS_TOOL

    @property
    def schema(self) -> ToolSchema:
        return self._SCHEMA

    async def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            data = ProgressEntryCreate.model_validate(dict(arguments))
        except ValidationError as exc:
            return ToolResult.error(f"Invalid progress entry: {_first_error(exc)}")
        entry = await self._service.add_progress(self._user_id, data, source=_AI_SOURCE)
        if entry is None:
            return ToolResult.error("Referenced goal/task not found for this user.")
        return ToolResult.ok({"logged": "progress", "id": entry.id, "note": entry.note})


def _first_error(exc: ValidationError) -> str:
    """A short, model-friendly rendering of the first pydantic validation error."""
    errors = exc.errors()
    if not errors:
        return "invalid arguments"
    first = errors[0]
    loc = ".".join(str(p) for p in first.get("loc", ())) or "arguments"
    return f"{loc}: {first.get('msg', 'invalid')}"
