"""Persistence seam for the dashboard (Postgres-backed in :mod:`app.repositories.dashboard_store`).

The living-PDP surface (§5.2) is one cohesive aggregate — ``goals → milestones → tasks`` plus an
append-only ``progress_entries`` log — so it gets **one** port here (rather than four narrow ones),
following the interface-before-implementation idiom used across the codebase (``ProfileStore``,
``PdpStore``, …): this module defines the :class:`DashboardStore` port plus a process-local
:class:`InMemoryDashboardStore` for tests; the **Postgres-backed** adapter
(:class:`~app.repositories.dashboard_store.PostgresDashboardStore`) lives in the repository layer.

**User-scoped by construction (§7 AuthZ).** Every method keys on the caller's ``users.id`` — there
is no path/body ``user_id`` a caller could point at another user. Child rows (milestones/tasks) are
reached only *through* an owned goal, and progress references are validated to belong to the caller,
so cross-user access reads as "not found" (``None``) rather than leaking or mutating another user's
row.

**Attribution is resolved by the caller, persisted verbatim here (§5.2).** The store does not decide
``source``/``status`` — the :class:`~app.services.dashboard.DashboardService` resolves them per
caller (this task's HTTP router → ``source="user"``; P8-03's tools → ``source="ai"`` +
``status="proposed"``) and hands the store fully-resolved values, keeping the human/AI attribution
policy in one place above the persistence seam.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.schemas.dashboard import (
    GoalCreate,
    GoalResponse,
    MilestoneCreate,
    MilestoneResponse,
    ProgressEntryCreate,
    ProgressEntryResponse,
    TaskCreate,
    TaskResponse,
)


@dataclass(frozen=True)
class DashboardSnapshot:
    """Everything needed to render ``GET /api/dashboard`` for one user, loaded in bulk.

    The service composes the nested/aggregated summary from this flat snapshot, so the Postgres
    adapter can load it in a few user-scoped queries instead of an N+1 walk of the hierarchy.
    """

    goals: list[GoalResponse] = field(default_factory=list)
    milestones: list[MilestoneResponse] = field(default_factory=list)
    tasks: list[TaskResponse] = field(default_factory=list)
    progress: list[ProgressEntryResponse] = field(default_factory=list)


class DashboardStore(ABC):
    """CRUD + bulk-read port for the dashboard aggregate (§5.2). All methods are user-scoped.

    ``create_*``/``update_*`` return the persisted response model; a read/update/delete that
    targets a row the user does not own returns ``None``/``False`` (never another user's data).
    ``status``/``source`` are supplied by the service (attribution policy lives there).
    """

    # --- goals -------------------------------------------------------------
    @abstractmethod
    async def create_goal(
        self, user_id: str, data: GoalCreate, *, status: str, source: str
    ) -> GoalResponse: ...

    @abstractmethod
    async def list_goals(self, user_id: str) -> list[GoalResponse]: ...

    @abstractmethod
    async def get_goal(self, user_id: str, goal_id: str) -> GoalResponse | None: ...

    @abstractmethod
    async def update_goal(
        self, user_id: str, goal_id: str, changes: dict[str, object]
    ) -> GoalResponse | None: ...

    @abstractmethod
    async def delete_goal(self, user_id: str, goal_id: str) -> bool: ...

    # --- milestones (reached through an owned goal) ------------------------
    @abstractmethod
    async def create_milestone(
        self, user_id: str, goal_id: str, data: MilestoneCreate, *, status: str, source: str
    ) -> MilestoneResponse | None: ...

    @abstractmethod
    async def list_milestones(self, user_id: str, goal_id: str) -> list[MilestoneResponse] | None:
        """List a goal's milestones, or ``None`` when the goal is missing/not owned."""

    @abstractmethod
    async def get_milestone(self, user_id: str, milestone_id: str) -> MilestoneResponse | None: ...

    @abstractmethod
    async def update_milestone(
        self, user_id: str, milestone_id: str, changes: dict[str, object]
    ) -> MilestoneResponse | None: ...

    @abstractmethod
    async def delete_milestone(self, user_id: str, milestone_id: str) -> bool: ...

    # --- tasks -------------------------------------------------------------
    @abstractmethod
    async def create_task(
        self, user_id: str, data: TaskCreate, *, status: str, source: str
    ) -> TaskResponse | None:
        """Create a task, or ``None`` when the goal (or milestone) is missing/not owned."""

    @abstractmethod
    async def list_tasks(self, user_id: str, goal_id: str | None = None) -> list[TaskResponse]: ...

    @abstractmethod
    async def get_task(self, user_id: str, task_id: str) -> TaskResponse | None: ...

    @abstractmethod
    async def update_task(
        self, user_id: str, task_id: str, changes: dict[str, object]
    ) -> TaskResponse | None: ...

    @abstractmethod
    async def delete_task(self, user_id: str, task_id: str) -> bool: ...

    # --- progress (append-only) --------------------------------------------
    @abstractmethod
    async def add_progress(
        self, user_id: str, data: ProgressEntryCreate, *, source: str
    ) -> ProgressEntryResponse | None:
        """Append an entry, or ``None`` when a referenced goal/task is missing/not owned."""

    @abstractmethod
    async def list_progress(
        self, user_id: str, *, limit: int, offset: int
    ) -> list[ProgressEntryResponse]: ...

    # --- bulk read for the summary -----------------------------------------
    @abstractmethod
    async def snapshot(self, user_id: str) -> DashboardSnapshot: ...


def _now() -> datetime:
    return datetime.now(UTC)


class InMemoryDashboardStore(DashboardStore):
    """Process-local :class:`DashboardStore` — test double only (mirrors DB scoping/cascades).

    Enforces the same user-scoping and parent-ownership rules as the Postgres adapter so the
    service's cross-user isolation is exercised without a real DB: milestones/tasks are reachable
    only through an owned goal; deleting a goal cascades to its milestones and tasks; deleting a
    milestone detaches (``SET NULL``) its tasks (they survive under the goal). Not for production.
    """

    def __init__(self) -> None:
        self._goals: dict[str, GoalResponse] = {}
        self._goal_owner: dict[str, str] = {}
        self._milestones: dict[str, MilestoneResponse] = {}
        self._tasks: dict[str, TaskResponse] = {}
        self._progress: dict[str, ProgressEntryResponse] = {}
        self._progress_owner: dict[str, str] = {}

    # --- goals -------------------------------------------------------------
    async def create_goal(
        self, user_id: str, data: GoalCreate, *, status: str, source: str
    ) -> GoalResponse:
        now = _now()
        goal = GoalResponse(
            id=uuid.uuid4().hex,
            title=data.title,
            target_role=data.target_role,
            target_date=data.target_date,
            status=status,
            source=source,
            created_at=now,
            updated_at=now,
        )
        self._goals[goal.id] = goal
        self._goal_owner[goal.id] = user_id
        return goal

    async def list_goals(self, user_id: str) -> list[GoalResponse]:
        return [g for gid, g in self._goals.items() if self._goal_owner.get(gid) == user_id]

    async def get_goal(self, user_id: str, goal_id: str) -> GoalResponse | None:
        if self._goal_owner.get(goal_id) != user_id:
            return None
        return self._goals.get(goal_id)

    async def update_goal(
        self, user_id: str, goal_id: str, changes: dict[str, object]
    ) -> GoalResponse | None:
        existing = await self.get_goal(user_id, goal_id)
        if existing is None:
            return None
        updated = existing.model_copy(update={**changes, "updated_at": _now()})
        self._goals[goal_id] = updated
        return updated

    async def delete_goal(self, user_id: str, goal_id: str) -> bool:
        if self._goal_owner.get(goal_id) != user_id:
            return False
        # Cascade to milestones + tasks under this goal (mirrors the FK cascade).
        for mid in [m.id for m in self._milestones.values() if m.goal_id == goal_id]:
            del self._milestones[mid]
        for tid in [t.id for t in self._tasks.values() if t.goal_id == goal_id]:
            del self._tasks[tid]
        del self._goals[goal_id]
        del self._goal_owner[goal_id]
        return True

    # --- milestones --------------------------------------------------------
    async def create_milestone(
        self, user_id: str, goal_id: str, data: MilestoneCreate, *, status: str, source: str
    ) -> MilestoneResponse | None:
        if await self.get_goal(user_id, goal_id) is None:
            return None
        now = _now()
        milestone = MilestoneResponse(
            id=uuid.uuid4().hex,
            goal_id=goal_id,
            title=data.title,
            due_date=data.due_date,
            status=status,
            source=source,
            created_at=now,
            updated_at=now,
        )
        self._milestones[milestone.id] = milestone
        return milestone

    def _owned_milestone(self, user_id: str, milestone_id: str) -> MilestoneResponse | None:
        m = self._milestones.get(milestone_id)
        if m is None or self._goal_owner.get(m.goal_id) != user_id:
            return None
        return m

    async def list_milestones(self, user_id: str, goal_id: str) -> list[MilestoneResponse] | None:
        if await self.get_goal(user_id, goal_id) is None:
            return None
        return [m for m in self._milestones.values() if m.goal_id == goal_id]

    async def get_milestone(self, user_id: str, milestone_id: str) -> MilestoneResponse | None:
        return self._owned_milestone(user_id, milestone_id)

    async def update_milestone(
        self, user_id: str, milestone_id: str, changes: dict[str, object]
    ) -> MilestoneResponse | None:
        existing = self._owned_milestone(user_id, milestone_id)
        if existing is None:
            return None
        updated = existing.model_copy(update={**changes, "updated_at": _now()})
        self._milestones[milestone_id] = updated
        return updated

    async def delete_milestone(self, user_id: str, milestone_id: str) -> bool:
        existing = self._owned_milestone(user_id, milestone_id)
        if existing is None:
            return False
        # SET NULL: detach the milestone's tasks (they survive under the goal).
        for tid, t in list(self._tasks.items()):
            if t.milestone_id == milestone_id:
                self._tasks[tid] = t.model_copy(update={"milestone_id": None})
        del self._milestones[milestone_id]
        return True

    # --- tasks -------------------------------------------------------------
    async def create_task(
        self, user_id: str, data: TaskCreate, *, status: str, source: str
    ) -> TaskResponse | None:
        if await self.get_goal(user_id, data.goal_id) is None:
            return None
        if data.milestone_id is not None:
            m = self._owned_milestone(user_id, data.milestone_id)
            if m is None or m.goal_id != data.goal_id:
                return None
        now = _now()
        task = TaskResponse(
            id=uuid.uuid4().hex,
            goal_id=data.goal_id,
            milestone_id=data.milestone_id,
            title=data.title,
            description=data.description,
            due_date=data.due_date,
            status=status,
            source=source,
            created_at=now,
            updated_at=now,
        )
        self._tasks[task.id] = task
        return task

    def _owned_task(self, user_id: str, task_id: str) -> TaskResponse | None:
        t = self._tasks.get(task_id)
        if t is None or self._goal_owner.get(t.goal_id) != user_id:
            return None
        return t

    async def list_tasks(self, user_id: str, goal_id: str | None = None) -> list[TaskResponse]:
        tasks = [t for t in self._tasks.values() if self._goal_owner.get(t.goal_id) == user_id]
        if goal_id is not None:
            tasks = [t for t in tasks if t.goal_id == goal_id]
        return tasks

    async def get_task(self, user_id: str, task_id: str) -> TaskResponse | None:
        return self._owned_task(user_id, task_id)

    async def update_task(
        self, user_id: str, task_id: str, changes: dict[str, object]
    ) -> TaskResponse | None:
        existing = self._owned_task(user_id, task_id)
        if existing is None:
            return None
        # A re-pointed milestone must be under the task's own goal (never another goal/user).
        new_milestone = changes.get("milestone_id", existing.milestone_id)
        if new_milestone is not None:
            m = self._owned_milestone(user_id, str(new_milestone))
            if m is None or m.goal_id != existing.goal_id:
                return None
        updated = existing.model_copy(update={**changes, "updated_at": _now()})
        self._tasks[task_id] = updated
        return updated

    async def delete_task(self, user_id: str, task_id: str) -> bool:
        if self._owned_task(user_id, task_id) is None:
            return False
        del self._tasks[task_id]
        return True

    # --- progress ----------------------------------------------------------
    async def add_progress(
        self, user_id: str, data: ProgressEntryCreate, *, source: str
    ) -> ProgressEntryResponse | None:
        if data.goal_id is not None and await self.get_goal(user_id, data.goal_id) is None:
            return None
        if data.task_id is not None and self._owned_task(user_id, data.task_id) is None:
            return None
        entry = ProgressEntryResponse(
            id=uuid.uuid4().hex,
            goal_id=data.goal_id,
            task_id=data.task_id,
            note=data.note,
            source=source,
            created_at=_now(),
        )
        self._progress[entry.id] = entry
        self._progress_owner[entry.id] = user_id
        return entry

    def _user_progress(self, user_id: str) -> list[ProgressEntryResponse]:
        entries = [
            e for eid, e in self._progress.items() if self._progress_owner.get(eid) == user_id
        ]
        # Newest first (mirrors the DB order by created_at DESC).
        return sorted(entries, key=lambda e: e.created_at, reverse=True)

    async def list_progress(
        self, user_id: str, *, limit: int, offset: int
    ) -> list[ProgressEntryResponse]:
        return self._user_progress(user_id)[offset : offset + limit]

    # --- bulk read ---------------------------------------------------------
    async def snapshot(self, user_id: str) -> DashboardSnapshot:
        return DashboardSnapshot(
            goals=await self.list_goals(user_id),
            milestones=[
                m for m in self._milestones.values() if self._goal_owner.get(m.goal_id) == user_id
            ],
            tasks=await self.list_tasks(user_id),
            progress=self._user_progress(user_id),
        )
