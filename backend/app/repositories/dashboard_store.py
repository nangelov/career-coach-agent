"""Postgres adapter for the :class:`~app.services.dashboard_store.DashboardStore` port (P8-02).

Maps the living-PDP CRUD surface (§5.2) onto the P8-01 ``goals``/``milestones``/``tasks``/
``progress_entries`` tables (:mod:`app.repositories.models.dashboard`). Lives in the repository
layer alongside those ORM models; all DB access goes through the shared
:class:`~app.repositories.postgres.PostgresConnectionProvider` (§4) — no ad-hoc engines. Routers
and the service depend only on the ``DashboardStore`` port, never on this adapter or SQLAlchemy
directly (§8 layering).

Two invariants enforced here:

* **User-scoping / parent-ownership (§7 AuthZ).** Every statement filters to the caller: goals by
  ``user_id`` directly, milestones/tasks by a join to their owning goal's ``user_id``, progress by
  ``user_id``. A row the caller does not own is simply not matched, so cross-user reads/writes
  return ``None``/``False`` (0 rows affected) instead of raising or touching another user's data. A
  malformed id fails safe as "not found" rather than erroring.
* **DB-level cascades own the hierarchy.** ``delete_goal`` is a single ``DELETE`` that relies on
  the ``ondelete="CASCADE"`` FKs (goal → milestones → tasks); ``delete_milestone`` relies on the
  ``ondelete="SET NULL"`` FK to detach (not delete) its tasks. Server-defaulted ``created_at`` /
  ``updated_at`` are read back via a refresh so the returned model carries the persisted values.
"""

from __future__ import annotations

import uuid
from typing import Any, TypeVar, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models.dashboard import DashboardTask, Goal, Milestone, ProgressEntry
from app.repositories.postgres import PostgresConnectionProvider
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
from app.services.dashboard_store import DashboardSnapshot, DashboardStore

_T = TypeVar("_T")


def _as_uuid(value: str) -> uuid.UUID | None:
    """Parse an id to UUID, or ``None`` (fail-safe: an unparseable id is "not found")."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


def _goal_to_response(row: Goal) -> GoalResponse:
    return GoalResponse(
        id=str(row.id),
        title=row.title,
        target_role=row.target_role,
        target_date=row.target_date,
        status=row.status,
        source=row.source,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _milestone_to_response(row: Milestone) -> MilestoneResponse:
    return MilestoneResponse(
        id=str(row.id),
        goal_id=str(row.goal_id),
        title=row.title,
        due_date=row.due_date,
        status=row.status,
        source=row.source,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _task_to_response(row: DashboardTask) -> TaskResponse:
    return TaskResponse(
        id=str(row.id),
        goal_id=str(row.goal_id),
        milestone_id=str(row.milestone_id) if row.milestone_id is not None else None,
        title=row.title,
        description=row.description,
        due_date=row.due_date,
        status=row.status,
        source=row.source,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _progress_to_response(row: ProgressEntry) -> ProgressEntryResponse:
    return ProgressEntryResponse(
        id=str(row.id),
        goal_id=str(row.goal_id) if row.goal_id is not None else None,
        task_id=str(row.task_id) if row.task_id is not None else None,
        note=row.note,
        source=row.source,
        created_at=row.created_at,
    )


class PostgresDashboardStore(DashboardStore):
    """Postgres-backed :class:`DashboardStore` over the P8-01 dashboard tables (§5.2)."""

    def __init__(self, provider: PostgresConnectionProvider) -> None:
        self._provider = provider

    @classmethod
    def from_provider(cls, provider: PostgresConnectionProvider) -> PostgresDashboardStore:
        """Build over the shared Postgres connection provider (§4)."""
        return cls(provider)

    @staticmethod
    async def _persist(db: AsyncSession, row: _T) -> _T:
        """Insert a new row and refresh it so server-defaulted columns are populated."""
        db.add(row)
        await db.flush()
        await db.refresh(row)
        await db.commit()
        return row

    async def _owned_goal(self, db: AsyncSession, user_id: str, goal_id: str) -> Goal | None:
        uid, gid = _as_uuid(user_id), _as_uuid(goal_id)
        if uid is None or gid is None:
            return None
        stmt = select(Goal).where(Goal.id == gid, Goal.user_id == uid)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def _owned_milestone(
        self, db: AsyncSession, user_id: str, milestone_id: str
    ) -> Milestone | None:
        uid, mid = _as_uuid(user_id), _as_uuid(milestone_id)
        if uid is None or mid is None:
            return None
        stmt = (
            select(Milestone)
            .join(Goal, Milestone.goal_id == Goal.id)
            .where(Milestone.id == mid, Goal.user_id == uid)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def _owned_task(
        self, db: AsyncSession, user_id: str, task_id: str
    ) -> DashboardTask | None:
        uid, tid = _as_uuid(user_id), _as_uuid(task_id)
        if uid is None or tid is None:
            return None
        stmt = (
            select(DashboardTask)
            .join(Goal, DashboardTask.goal_id == Goal.id)
            .where(DashboardTask.id == tid, Goal.user_id == uid)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    # --- goals -------------------------------------------------------------
    async def create_goal(
        self, user_id: str, data: GoalCreate, *, status: str, source: str
    ) -> GoalResponse:
        row = Goal(
            user_id=uuid.UUID(user_id),
            title=data.title,
            target_role=data.target_role,
            target_date=data.target_date,
            status=status,
            source=source,
        )
        async with self._provider.session() as db:
            await self._persist(db, row)
        return _goal_to_response(row)

    async def list_goals(self, user_id: str) -> list[GoalResponse]:
        uid = _as_uuid(user_id)
        if uid is None:
            return []
        stmt = select(Goal).where(Goal.user_id == uid).order_by(Goal.created_at)
        async with self._provider.session() as db:
            rows = (await db.execute(stmt)).scalars().all()
        return [_goal_to_response(r) for r in rows]

    async def get_goal(self, user_id: str, goal_id: str) -> GoalResponse | None:
        async with self._provider.session() as db:
            row = await self._owned_goal(db, user_id, goal_id)
        return _goal_to_response(row) if row is not None else None

    async def update_goal(
        self, user_id: str, goal_id: str, changes: dict[str, object]
    ) -> GoalResponse | None:
        async with self._provider.session() as db:
            row = await self._owned_goal(db, user_id, goal_id)
            if row is None:
                return None
            for field_name, value in changes.items():
                setattr(row, field_name, value)
            await db.flush()
            await db.refresh(row)
            await db.commit()
            return _goal_to_response(row)

    async def delete_goal(self, user_id: str, goal_id: str) -> bool:
        uid, gid = _as_uuid(user_id), _as_uuid(goal_id)
        if uid is None or gid is None:
            return False
        stmt = delete(Goal).where(Goal.id == gid, Goal.user_id == uid)
        async with self._provider.session() as db:
            result = await db.execute(stmt)
            await db.commit()
        return cast("CursorResult[Any]", result).rowcount > 0

    # --- milestones --------------------------------------------------------
    async def create_milestone(
        self, user_id: str, goal_id: str, data: MilestoneCreate, *, status: str, source: str
    ) -> MilestoneResponse | None:
        async with self._provider.session() as db:
            goal = await self._owned_goal(db, user_id, goal_id)
            if goal is None:
                return None
            row = Milestone(
                goal_id=goal.id,
                title=data.title,
                due_date=data.due_date,
                status=status,
                source=source,
            )
            await self._persist(db, row)
        return _milestone_to_response(row)

    async def list_milestones(self, user_id: str, goal_id: str) -> list[MilestoneResponse] | None:
        async with self._provider.session() as db:
            goal = await self._owned_goal(db, user_id, goal_id)
            if goal is None:
                return None
            stmt = (
                select(Milestone).where(Milestone.goal_id == goal.id).order_by(Milestone.created_at)
            )
            rows = (await db.execute(stmt)).scalars().all()
        return [_milestone_to_response(r) for r in rows]

    async def get_milestone(self, user_id: str, milestone_id: str) -> MilestoneResponse | None:
        async with self._provider.session() as db:
            row = await self._owned_milestone(db, user_id, milestone_id)
        return _milestone_to_response(row) if row is not None else None

    async def update_milestone(
        self, user_id: str, milestone_id: str, changes: dict[str, object]
    ) -> MilestoneResponse | None:
        async with self._provider.session() as db:
            row = await self._owned_milestone(db, user_id, milestone_id)
            if row is None:
                return None
            for field_name, value in changes.items():
                setattr(row, field_name, value)
            await db.flush()
            await db.refresh(row)
            await db.commit()
            return _milestone_to_response(row)

    async def delete_milestone(self, user_id: str, milestone_id: str) -> bool:
        uid, mid = _as_uuid(user_id), _as_uuid(milestone_id)
        if uid is None or mid is None:
            return False
        # Scope by ownership through the parent goal; the FK ``SET NULL`` detaches its tasks.
        stmt = delete(Milestone).where(
            Milestone.id == mid,
            Milestone.goal_id.in_(select(Goal.id).where(Goal.user_id == uid)),
        )
        async with self._provider.session() as db:
            result = await db.execute(stmt)
            await db.commit()
        return cast("CursorResult[Any]", result).rowcount > 0

    # --- tasks -------------------------------------------------------------
    async def create_task(
        self, user_id: str, data: TaskCreate, *, status: str, source: str
    ) -> TaskResponse | None:
        async with self._provider.session() as db:
            goal = await self._owned_goal(db, user_id, data.goal_id)
            if goal is None:
                return None
            milestone_uuid: uuid.UUID | None = None
            if data.milestone_id is not None:
                milestone = await self._owned_milestone(db, user_id, data.milestone_id)
                # The milestone must exist, be owned, and sit under the *same* goal.
                if milestone is None or milestone.goal_id != goal.id:
                    return None
                milestone_uuid = milestone.id
            row = DashboardTask(
                goal_id=goal.id,
                milestone_id=milestone_uuid,
                title=data.title,
                description=data.description,
                due_date=data.due_date,
                status=status,
                source=source,
            )
            await self._persist(db, row)
        return _task_to_response(row)

    async def list_tasks(self, user_id: str, goal_id: str | None = None) -> list[TaskResponse]:
        uid = _as_uuid(user_id)
        if uid is None:
            return []
        stmt = (
            select(DashboardTask)
            .join(Goal, DashboardTask.goal_id == Goal.id)
            .where(Goal.user_id == uid)
            .order_by(DashboardTask.created_at)
        )
        if goal_id is not None:
            gid = _as_uuid(goal_id)
            if gid is None:
                return []
            stmt = stmt.where(DashboardTask.goal_id == gid)
        async with self._provider.session() as db:
            rows = (await db.execute(stmt)).scalars().all()
        return [_task_to_response(r) for r in rows]

    async def get_task(self, user_id: str, task_id: str) -> TaskResponse | None:
        async with self._provider.session() as db:
            row = await self._owned_task(db, user_id, task_id)
        return _task_to_response(row) if row is not None else None

    async def update_task(
        self, user_id: str, task_id: str, changes: dict[str, object]
    ) -> TaskResponse | None:
        async with self._provider.session() as db:
            row = await self._owned_task(db, user_id, task_id)
            if row is None:
                return None
            # A re-pointed milestone must be owned and under the task's own goal.
            if "milestone_id" in changes:
                new_milestone_id = changes["milestone_id"]
                if new_milestone_id is None:
                    row.milestone_id = None
                else:
                    milestone = await self._owned_milestone(db, user_id, str(new_milestone_id))
                    if milestone is None or milestone.goal_id != row.goal_id:
                        return None
                    row.milestone_id = milestone.id
            for field_name, value in changes.items():
                if field_name == "milestone_id":
                    continue
                setattr(row, field_name, value)
            await db.flush()
            await db.refresh(row)
            await db.commit()
            return _task_to_response(row)

    async def delete_task(self, user_id: str, task_id: str) -> bool:
        uid, tid = _as_uuid(user_id), _as_uuid(task_id)
        if uid is None or tid is None:
            return False
        stmt = delete(DashboardTask).where(
            DashboardTask.id == tid,
            DashboardTask.goal_id.in_(select(Goal.id).where(Goal.user_id == uid)),
        )
        async with self._provider.session() as db:
            result = await db.execute(stmt)
            await db.commit()
        return cast("CursorResult[Any]", result).rowcount > 0

    # --- progress ----------------------------------------------------------
    async def add_progress(
        self, user_id: str, data: ProgressEntryCreate, *, source: str
    ) -> ProgressEntryResponse | None:
        uid = _as_uuid(user_id)
        if uid is None:
            return None
        async with self._provider.session() as db:
            goal_uuid: uuid.UUID | None = None
            if data.goal_id is not None:
                goal = await self._owned_goal(db, user_id, data.goal_id)
                if goal is None:
                    return None
                goal_uuid = goal.id
            task_uuid: uuid.UUID | None = None
            if data.task_id is not None:
                task = await self._owned_task(db, user_id, data.task_id)
                if task is None:
                    return None
                task_uuid = task.id
            row = ProgressEntry(
                user_id=uid,
                goal_id=goal_uuid,
                task_id=task_uuid,
                note=data.note,
                source=source,
            )
            await self._persist(db, row)
        return _progress_to_response(row)

    async def list_progress(
        self, user_id: str, *, limit: int, offset: int
    ) -> list[ProgressEntryResponse]:
        uid = _as_uuid(user_id)
        if uid is None:
            return []
        stmt = (
            select(ProgressEntry)
            .where(ProgressEntry.user_id == uid)
            .order_by(ProgressEntry.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._provider.session() as db:
            rows = (await db.execute(stmt)).scalars().all()
        return [_progress_to_response(r) for r in rows]

    # --- bulk read ---------------------------------------------------------
    async def snapshot(self, user_id: str) -> DashboardSnapshot:
        uid = _as_uuid(user_id)
        if uid is None:
            return DashboardSnapshot()
        goals_stmt = select(Goal).where(Goal.user_id == uid).order_by(Goal.created_at)
        milestones_stmt = (
            select(Milestone)
            .join(Goal, Milestone.goal_id == Goal.id)
            .where(Goal.user_id == uid)
            .order_by(Milestone.created_at)
        )
        tasks_stmt = (
            select(DashboardTask)
            .join(Goal, DashboardTask.goal_id == Goal.id)
            .where(Goal.user_id == uid)
            .order_by(DashboardTask.created_at)
        )
        progress_stmt = (
            select(ProgressEntry)
            .where(ProgressEntry.user_id == uid)
            .order_by(ProgressEntry.created_at.desc())
        )
        async with self._provider.session() as db:
            goals = (await db.execute(goals_stmt)).scalars().all()
            milestones = (await db.execute(milestones_stmt)).scalars().all()
            tasks = (await db.execute(tasks_stmt)).scalars().all()
            progress = (await db.execute(progress_stmt)).scalars().all()
        return DashboardSnapshot(
            goals=[_goal_to_response(r) for r in goals],
            milestones=[_milestone_to_response(r) for r in milestones],
            tasks=[_task_to_response(r) for r in tasks],
            progress=[_progress_to_response(r) for r in progress],
        )
