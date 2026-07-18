"""Integration checks for :class:`PostgresDashboardStore` against **real Postgres** (P8-02).

Proves the dashboard adapter round-trips through the P8-01 ``goals``/``milestones``/``tasks``/
``progress_entries`` tables and that the DB-level scoping/cascades hold: user-scoping (a second
user never sees the first's rows), goal-delete cascades to milestones + tasks, and milestone-delete
detaches (``SET NULL``) its tasks. Requires the docker-compose Postgres (JSONB/UUID/date types
SQLite cannot represent) and real ``users`` rows for the FK anchors; **skips automatically** when no
Postgres is reachable so free-tier CI without a DB stays green. Each test deletes the throwaway
users it created (GDPR cascade removes their dashboard rows too, §4), leaving the DB as found.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.repositories.dashboard_store import PostgresDashboardStore
from app.repositories.models.dashboard import DashboardTask, Goal, Milestone
from app.repositories.models.identity import User
from app.repositories.postgres import PostgresConnectionProvider
from app.schemas.dashboard import (
    GoalCreate,
    MilestoneCreate,
    ProgressEntryCreate,
    TaskCreate,
)


async def _postgres_reachable() -> bool:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect():
            return True
    except Exception:  # noqa: BLE001 - any connect failure → skip, never error the suite
        return False
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def provider() -> AsyncIterator[PostgresConnectionProvider]:
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — integration test skipped")
    prov = PostgresConnectionProvider.from_settings(settings)
    try:
        async with prov.session() as db:
            await db.execute(select(Goal).limit(1))
    except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
        await prov.aclose()
        pytest.skip("dashboard schema not applied — run `alembic upgrade head`")
    try:
        yield prov
    finally:
        await prov.aclose()


async def _create_user(provider: PostgresConnectionProvider) -> str:
    async with provider.session() as db:
        user = User(
            provider="google",
            sub=f"sub-{uuid4().hex[:12]}",
            email=f"{uuid4().hex[:8]}@example.com",
            display_name="Dashboard Test",
        )
        db.add(user)
        await db.commit()
        return str(user.id)


async def _delete_user(provider: PostgresConnectionProvider, user_id: str) -> None:
    async with provider.session() as db:
        existing = await db.get(User, uuid.UUID(user_id))
        if existing is not None:
            await db.delete(existing)
            await db.commit()


async def test_goal_milestone_task_progress_roundtrip(
    provider: PostgresConnectionProvider,
) -> None:
    store = PostgresDashboardStore(provider)
    user_id = await _create_user(provider)
    try:
        goal = await store.create_goal(
            user_id, GoalCreate(title="Staff Engineer"), status="active", source="user"
        )
        assert goal.status == "active"
        assert goal.source == "user"
        assert goal.created_at is not None

        # Approve-style edit persists.
        updated = await store.update_goal(user_id, goal.id, {"status": "completed"})
        assert updated is not None and updated.status == "completed"

        milestone = await store.create_milestone(
            user_id, goal.id, MilestoneCreate(title="M1"), status="pending", source="user"
        )
        assert milestone is not None and milestone.goal_id == goal.id

        task = await store.create_task(
            user_id,
            TaskCreate(goal_id=goal.id, milestone_id=milestone.id, title="T1"),
            status="todo",
            source="user",
        )
        assert task is not None and task.milestone_id == milestone.id

        entry = await store.add_progress(
            user_id,
            ProgressEntryCreate(goal_id=goal.id, task_id=task.id, note="did it"),
            source="user",
        )
        assert entry is not None

        snapshot = await store.snapshot(user_id)
        assert len(snapshot.goals) == 1
        assert len(snapshot.milestones) == 1
        assert len(snapshot.tasks) == 1
        assert len(snapshot.progress) == 1
    finally:
        await _delete_user(provider, user_id)


async def test_cross_user_scoping(provider: PostgresConnectionProvider) -> None:
    store = PostgresDashboardStore(provider)
    user_a = await _create_user(provider)
    user_b = await _create_user(provider)
    try:
        goal = await store.create_goal(
            user_a, GoalCreate(title="A-secret"), status="active", source="user"
        )
        # B sees nothing of A's and cannot touch it.
        assert await store.get_goal(user_b, goal.id) is None
        assert await store.update_goal(user_b, goal.id, {"title": "x"}) is None
        assert await store.delete_goal(user_b, goal.id) is False
        assert await store.list_goals(user_b) == []
        # A still owns an untouched goal.
        still = await store.get_goal(user_a, goal.id)
        assert still is not None and still.title == "A-secret"
    finally:
        await _delete_user(provider, user_a)
        await _delete_user(provider, user_b)


async def test_delete_goal_cascades_and_milestone_detaches(
    provider: PostgresConnectionProvider,
) -> None:
    store = PostgresDashboardStore(provider)
    user_id = await _create_user(provider)
    try:
        goal = await store.create_goal(
            user_id, GoalCreate(title="G"), status="active", source="user"
        )
        milestone = await store.create_milestone(
            user_id, goal.id, MilestoneCreate(title="M"), status="pending", source="user"
        )
        assert milestone is not None
        task = await store.create_task(
            user_id,
            TaskCreate(goal_id=goal.id, milestone_id=milestone.id, title="T"),
            status="todo",
            source="user",
        )
        assert task is not None

        # Deleting the milestone detaches (SET NULL) its task — the task survives.
        assert await store.delete_milestone(user_id, milestone.id) is True
        detached = await store.get_task(user_id, task.id)
        assert detached is not None and detached.milestone_id is None

        # Deleting the goal cascades to remaining tasks (and any milestones).
        assert await store.delete_goal(user_id, goal.id) is True
        async with provider.session() as db:
            goal_uuid = uuid.UUID(goal.id)
            remaining_tasks = (
                (await db.execute(select(DashboardTask).where(DashboardTask.goal_id == goal_uuid)))
                .scalars()
                .all()
            )
            remaining_ms = (
                (await db.execute(select(Milestone).where(Milestone.goal_id == goal_uuid)))
                .scalars()
                .all()
            )
        assert remaining_tasks == []
        assert remaining_ms == []
    finally:
        await _delete_user(provider, user_id)
