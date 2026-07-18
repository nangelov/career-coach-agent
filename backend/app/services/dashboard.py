"""Dashboard service — CRUD orchestration + summary aggregation over the living PDP (P8-02, §5.2).

The **policy** layer behind the thin ``/api/dashboard`` router (Router → Service → Repository, §8):
it owns the dashboard business logic so the router stays HTTP-only. Two responsibilities beyond
plain delegation to the :class:`~app.services.dashboard_store.DashboardStore` port:

* **Attribution resolution (§5.2).** The store persists ``source``/``status`` verbatim; this
  service decides them per caller so the policy lives in one place. Every write defaults to
  ``source="user"`` with the entity's normal starting status — the human CRUD path. The same
  methods take ``source="ai"`` (P8-03's native tools), which defaults the status to ``proposed``
  (the pending-approval state), so the AI-propose workflow reuses this service unchanged. A user
  ``PATCH`` that moves a ``proposed`` row to a normal status is the "approve" action; a user
  ``DELETE`` of a ``proposed`` row is "reject" (task §"proposed status semantics").

* **Summary aggregation (``GET /api/dashboard``).** Nests each goal's milestones + tasks and
  derives a first-cut progress view: elapsed-time percent toward each goal's ``target_date``
  (date-arithmetic, no stored column), task completion percent, and a progress/streak rollup over
  the append-only ``progress_entries`` log. Unit-testable against the in-memory store.

Cross-user access is denied at the store (every method is user-scoped); a miss surfaces as ``None``
here, which the router maps to ``404`` — never leaking another user's row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.schemas.dashboard import (
    DashboardSummary,
    GoalCreate,
    GoalResponse,
    GoalSummary,
    GoalUpdate,
    MilestoneCreate,
    MilestoneResponse,
    MilestoneUpdate,
    ProgressEntryCreate,
    ProgressEntryResponse,
    ProgressSummary,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
)
from app.services.dashboard_store import DashboardSnapshot, DashboardStore

__all__ = ["DashboardService"]

#: Starting status for a **user**-created row of each kind (mirrors the ORM server defaults). An
#: AI-created row instead starts ``proposed`` (pending user approval, §5.2) — resolved below.
_USER_DEFAULT_STATUS = {"goal": "active", "milestone": "pending", "task": "todo"}
_AI_PROPOSED_STATUS = "proposed"

#: Trailing window (days, inclusive of today) for the "recent activity" count in the summary.
_RECENT_WINDOW_DAYS = 7


@dataclass(frozen=True)
class DashboardService:
    """CRUD + summary orchestration over a :class:`DashboardStore` (Router → Service → Repo, §8).

    Stateless beyond its injected store, so the same instance serves the HTTP router (this task)
    and P8-03's native tools (``source="ai"``). Built once by the composition root
    (:func:`app.bootstrap.build_dashboard_service`).
    """

    store: DashboardStore

    @staticmethod
    def _resolve_status(kind: str, source: str) -> str:
        """Resolve the starting status for a new row from its kind + attribution (§5.2)."""
        return _AI_PROPOSED_STATUS if source == "ai" else _USER_DEFAULT_STATUS[kind]

    # --- goals -------------------------------------------------------------
    async def create_goal(
        self, user_id: str, data: GoalCreate, *, source: str = "user"
    ) -> GoalResponse:
        return await self.store.create_goal(
            user_id, data, status=self._resolve_status("goal", source), source=source
        )

    async def list_goals(self, user_id: str) -> list[GoalResponse]:
        return await self.store.list_goals(user_id)

    async def get_goal(self, user_id: str, goal_id: str) -> GoalResponse | None:
        return await self.store.get_goal(user_id, goal_id)

    async def update_goal(
        self, user_id: str, goal_id: str, data: GoalUpdate
    ) -> GoalResponse | None:
        return await self.store.update_goal(user_id, goal_id, data.model_dump(exclude_unset=True))

    async def delete_goal(self, user_id: str, goal_id: str) -> bool:
        return await self.store.delete_goal(user_id, goal_id)

    # --- milestones --------------------------------------------------------
    async def create_milestone(
        self, user_id: str, goal_id: str, data: MilestoneCreate, *, source: str = "user"
    ) -> MilestoneResponse | None:
        return await self.store.create_milestone(
            user_id, goal_id, data, status=self._resolve_status("milestone", source), source=source
        )

    async def list_milestones(self, user_id: str, goal_id: str) -> list[MilestoneResponse] | None:
        return await self.store.list_milestones(user_id, goal_id)

    async def get_milestone(self, user_id: str, milestone_id: str) -> MilestoneResponse | None:
        return await self.store.get_milestone(user_id, milestone_id)

    async def update_milestone(
        self, user_id: str, milestone_id: str, data: MilestoneUpdate
    ) -> MilestoneResponse | None:
        return await self.store.update_milestone(
            user_id, milestone_id, data.model_dump(exclude_unset=True)
        )

    async def delete_milestone(self, user_id: str, milestone_id: str) -> bool:
        return await self.store.delete_milestone(user_id, milestone_id)

    # --- tasks -------------------------------------------------------------
    async def create_task(
        self, user_id: str, data: TaskCreate, *, source: str = "user"
    ) -> TaskResponse | None:
        return await self.store.create_task(
            user_id, data, status=self._resolve_status("task", source), source=source
        )

    async def list_tasks(self, user_id: str, goal_id: str | None = None) -> list[TaskResponse]:
        return await self.store.list_tasks(user_id, goal_id)

    async def get_task(self, user_id: str, task_id: str) -> TaskResponse | None:
        return await self.store.get_task(user_id, task_id)

    async def update_task(
        self, user_id: str, task_id: str, data: TaskUpdate
    ) -> TaskResponse | None:
        return await self.store.update_task(user_id, task_id, data.model_dump(exclude_unset=True))

    async def delete_task(self, user_id: str, task_id: str) -> bool:
        return await self.store.delete_task(user_id, task_id)

    # --- progress ----------------------------------------------------------
    async def add_progress(
        self, user_id: str, data: ProgressEntryCreate, *, source: str = "user"
    ) -> ProgressEntryResponse | None:
        return await self.store.add_progress(user_id, data, source=source)

    async def list_progress(
        self, user_id: str, *, limit: int, offset: int
    ) -> list[ProgressEntryResponse]:
        return await self.store.list_progress(user_id, limit=limit, offset=offset)

    # --- summary -----------------------------------------------------------
    async def get_summary(self, user_id: str) -> DashboardSummary:
        """Aggregate the caller's goals (nested) + progress/streak rollup (the summary endpoint)."""
        snapshot = await self.store.snapshot(user_id)
        today = datetime.now(UTC).date()
        goals = [self._summarize_goal(goal, snapshot, today) for goal in snapshot.goals]
        return DashboardSummary(
            goals=goals, progress=self._summarize_progress(snapshot.progress, today)
        )

    @staticmethod
    def _summarize_goal(
        goal: GoalResponse, snapshot: DashboardSnapshot, today: date
    ) -> GoalSummary:
        milestones = [m for m in snapshot.milestones if m.goal_id == goal.id]
        tasks = [t for t in snapshot.tasks if t.goal_id == goal.id]
        return GoalSummary(
            **goal.model_dump(),
            milestones=milestones,
            tasks=tasks,
            time_progress_pct=_time_progress_pct(goal.created_at.date(), goal.target_date, today),
            task_completion_pct=_task_completion_pct(tasks),
        )

    @staticmethod
    def _summarize_progress(entries: list[ProgressEntryResponse], today: date) -> ProgressSummary:
        entry_days = [e.created_at.date() for e in entries]
        cutoff = today.toordinal() - (_RECENT_WINDOW_DAYS - 1)
        recent = sum(1 for d in entry_days if d.toordinal() >= cutoff)
        day_set = set(entry_days)
        return ProgressSummary(
            total_entries=len(entries),
            entries_last_7_days=recent,
            current_streak_days=_current_streak(day_set, today),
            last_entry_date=max(day_set) if day_set else None,
        )


def _time_progress_pct(created: date, target: date | None, today: date) -> float | None:
    """Elapsed-time percent (0–100) from ``created`` toward ``target``; ``None`` if no target.

    Pure date-arithmetic (no stored column, task §"summary"): a goal with no ``target_date`` yields
    ``None`` (nothing to measure against); a non-future target that has already passed clamps to
    ``100``; a degenerate span (target ≤ created) is treated as complete.
    """
    if target is None:
        return None
    span = (target - created).days
    if span <= 0:
        return 100.0
    elapsed = (today - created).days
    return round(max(0.0, min(1.0, elapsed / span)) * 100, 1)


def _task_completion_pct(tasks: list[TaskResponse]) -> float | None:
    """Percent of a goal's tasks that are ``done`` (0–100), or ``None`` when it has no tasks."""
    if not tasks:
        return None
    done = sum(1 for t in tasks if t.status == "done")
    return round(done / len(tasks) * 100, 1)


def _current_streak(days: set[date], today: date) -> int:
    """Count consecutive days of activity ending today (or yesterday, if today has no entry yet).

    A first-cut streak (task §"summary"): if the most recent activity is neither today nor
    yesterday the streak is broken (``0``); otherwise walk back day-by-day while each prior day has
    an entry. Anchoring on yesterday-too avoids resetting a streak just because the user has not
    logged *yet* today.
    """
    if today in days:
        cursor = today
    elif date.fromordinal(today.toordinal() - 1) in days:
        cursor = date.fromordinal(today.toordinal() - 1)
    else:
        return 0
    streak = 0
    while cursor in days:
        streak += 1
        cursor = date.fromordinal(cursor.toordinal() - 1)
    return streak
