"""Dashboard API contract — goals/milestones/tasks/progress + summary (P8-02, §5.2 / §9).

The typed request/response shapes the thin ``/api/dashboard`` router trades in and the
:class:`~app.services.dashboard.DashboardService` returns. The living-PDP surface (§5.2) is a
``goals → milestones → tasks`` hierarchy plus an append-only ``progress_entries`` log; these
models mirror the P8-01 ORM (:mod:`app.repositories.models.dashboard`) as an HTTP contract.

Two boundary decisions are encoded here (task §"Auth + attribution"):

* **The human status vocabularies exclude ``proposed``.** ``proposed`` is the pending-approval
  state reserved for *AI-proposed* rows (P8-03's native tools). A human ``PATCH`` never sets it,
  so the ``*Update`` models' ``status`` literals omit it — keeping the human/AI attribution
  honest at the wire boundary rather than trusting a client-sent value. Response models carry
  ``status`` as a plain ``str`` because an AI-created row *can* be ``proposed`` when read back.
* **No client-sent ``source``.** ``source`` (``user`` | ``ai``) is set server-side per caller —
  this router always writes ``source="user"`` — so it is a response-only field, never accepted on
  a create/update body.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "GoalCreate",
    "GoalResponse",
    "GoalStatus",
    "GoalSummary",
    "GoalUpdate",
    "MilestoneCreate",
    "MilestoneResponse",
    "MilestoneStatus",
    "MilestoneUpdate",
    "ProgressEntryCreate",
    "ProgressEntryResponse",
    "ProgressSummary",
    "DashboardSummary",
    "TaskCreate",
    "TaskResponse",
    "TaskStatus",
    "TaskUpdate",
]

#: Human-settable goal statuses (the ORM vocabulary minus ``proposed`` — see module docstring).
GoalStatus = Literal["active", "completed", "abandoned"]
#: Human-settable milestone statuses (ORM vocabulary minus ``proposed``).
MilestoneStatus = Literal["pending", "in_progress", "completed"]
#: Human-settable task statuses (ORM vocabulary minus ``proposed``).
TaskStatus = Literal["todo", "in_progress", "done", "cancelled"]


# --------------------------------------------------------------------------- goals
class GoalCreate(BaseModel):
    """``POST /api/dashboard/goals`` body — a new career goal (status/source set server-side)."""

    title: str = Field(..., min_length=1, max_length=512)
    target_role: str | None = Field(default=None, max_length=512)
    target_date: date | None = Field(
        default=None, description="Optional target date the plan's timeline aims at."
    )


class GoalUpdate(BaseModel):
    """``PATCH /api/dashboard/goals/{id}`` body — partial edit; only provided fields change.

    Setting ``status`` on an AI-``proposed`` goal (to any allowed value here — all non-proposed)
    is exactly the "approve" action (task §"proposed status semantics"); no separate endpoint.
    """

    title: str | None = Field(default=None, min_length=1, max_length=512)
    target_role: str | None = Field(default=None, max_length=512)
    target_date: date | None = None
    status: GoalStatus | None = None


class GoalResponse(BaseModel):
    """A persisted goal (§5.2). ``status``/``source`` are plain ``str`` — a read may be AI-made."""

    id: str
    title: str
    target_role: str | None
    target_date: date | None
    status: str
    source: str
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------------- milestones
class MilestoneCreate(BaseModel):
    """``POST /api/dashboard/goals/{goal_id}/milestones`` body — a checkpoint under a goal."""

    title: str = Field(..., min_length=1, max_length=512)
    due_date: date | None = None


class MilestoneUpdate(BaseModel):
    """``PATCH /api/dashboard/milestones/{id}`` body — partial edit / approve (status change)."""

    title: str | None = Field(default=None, min_length=1, max_length=512)
    due_date: date | None = None
    status: MilestoneStatus | None = None


class MilestoneResponse(BaseModel):
    """A persisted milestone (§5.2) under its goal."""

    id: str
    goal_id: str
    title: str
    due_date: date | None
    status: str
    source: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------- tasks
class TaskCreate(BaseModel):
    """``POST /api/dashboard/tasks`` body — a task anchored to a goal (milestone optional).

    ``goal_id`` is required (every task belongs to a goal, per the P8-01 schema); ``milestone_id``
    is optional (a task can exist before any milestone is set).
    """

    goal_id: str = Field(..., min_length=1)
    milestone_id: str | None = Field(default=None, min_length=1)
    title: str = Field(..., min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=8000)
    due_date: date | None = None


class TaskUpdate(BaseModel):
    """``PATCH /api/dashboard/tasks/{id}`` body — partial edit / approve (status change).

    ``milestone_id`` may be re-pointed (or cleared) but always within the caller's own goal — the
    service rejects a milestone that is not under the task's goal.
    """

    milestone_id: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=8000)
    due_date: date | None = None
    status: TaskStatus | None = None


class TaskResponse(BaseModel):
    """A persisted dashboard task (§5.2)."""

    id: str
    goal_id: str
    milestone_id: str | None
    title: str
    description: str | None
    due_date: date | None
    status: str
    source: str
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------------- progress
class ProgressEntryCreate(BaseModel):
    """``POST /api/dashboard/progress`` body — append a progress/check-in entry (append-only).

    Optionally references a goal and/or task; both are validated to belong to the caller.
    """

    goal_id: str | None = Field(default=None, min_length=1)
    task_id: str | None = Field(default=None, min_length=1)
    note: str | None = Field(default=None, max_length=8000)


class ProgressEntryResponse(BaseModel):
    """A persisted progress-log entry (§5.2 — trend/streak views). No update path (append-only)."""

    id: str
    goal_id: str | None
    task_id: str | None
    note: str | None
    source: str
    created_at: datetime


# -------------------------------------------------------------------------- summary
class GoalSummary(GoalResponse):
    """A goal with its nested milestones + tasks and derived progress (``GET /api/dashboard``).

    ``time_progress_pct`` is elapsed time toward ``target_date`` (0–100, date-arithmetic, no
    stored column); ``task_completion_pct`` is ``done`` tasks over total. Both are ``None`` when
    not computable (no target date / no tasks).
    """

    milestones: list[MilestoneResponse] = Field(default_factory=list)
    tasks: list[TaskResponse] = Field(default_factory=list)
    time_progress_pct: float | None = None
    task_completion_pct: float | None = None


class ProgressSummary(BaseModel):
    """A first-cut progress/streak rollup over the caller's ``progress_entries`` (§5.2)."""

    total_entries: int
    entries_last_7_days: int
    current_streak_days: int
    last_entry_date: date | None


class DashboardSummary(BaseModel):
    """The ``GET /api/dashboard`` response — goals (nested) + a progress/streak summary."""

    goals: list[GoalSummary]
    progress: ProgressSummary
