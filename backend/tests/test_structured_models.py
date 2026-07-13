"""Integration checks for the P2-05 structured-records schema against **real Postgres**.

Proves the PDP / dashboard table group created by migration ``0004`` is usable: JSONB
round-trips, checked ``status`` / ``source`` vocabularies are enforced, and the cascade
rules behave — in particular the §4 GDPR cascades (user → goals → milestones → tasks,
user → pdps / progress_entries) and the §5.2 attribution/append-only posture.

(The ``jobs`` table was renamed to ``job_postings`` and rescoped into the market-intel
group in P6-02 — its checks now live in ``test_market_models.py``.)

They require the docker-compose Postgres (``JSONB``/``UUID`` cannot be represented in
SQLite). The suite is **skipped automatically** when no Postgres is reachable at
``DATABASE_URL`` (so free-tier CI without a DB service stays green), and runs entirely inside
a single transaction that is rolled back at the end, leaving the database untouched.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.repositories.models import (
    DashboardTask,
    Goal,
    Milestone,
    Pdp,
    ProgressEntry,
    User,
)


async def _postgres_reachable() -> bool:
    """True if the configured Postgres accepts a connection (else the suite skips)."""
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect():
            return True
    except Exception:  # noqa: BLE001 - any connect failure → skip, never error the suite
        return False
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A session whose outer transaction is rolled back, leaving the DB untouched.

    Skips the whole test if Postgres is unreachable or the ``0004`` schema is not applied
    (this suite verifies the *applied* migration, it does not create the schema itself).
    """
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — integration test skipped")

    engine = create_async_engine(settings.DATABASE_URL)
    conn = await engine.connect()
    trans = await conn.begin()
    db = AsyncSession(bind=conn, expire_on_commit=False)
    try:
        try:
            await db.execute(select(Pdp).limit(1))
        except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
            pytest.skip(
                "structured schema (migration 0004) not applied — run `alembic upgrade head`"
            )
        yield db
    finally:
        await db.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()


def _make_user() -> User:
    unique = uuid4().hex[:12]
    return User(
        provider="google",
        sub=f"sub-{unique}",
        email=f"user-{unique}@example.com",
        display_name="Test User",
    )


async def test_pdp_round_trip_and_user_cascade(session: AsyncSession) -> None:
    """A PDP stores regeneration data (JSONB) and is erased on user-delete (§4)."""
    user = _make_user()
    session.add(user)
    await session.flush()
    pdp = Pdp(
        user_id=user.id,
        career_goal="Become a staff engineer",
        target_date=date(2027, 1, 1),
        content={"sections": {"skills": "…", "plan": "…"}},
    )
    session.add(pdp)
    await session.flush()
    pdp_id, user_id = pdp.id, user.id
    session.expire_all()

    fetched = (await session.execute(select(Pdp).where(Pdp.id == pdp_id))).scalar_one()
    assert fetched.content == {"sections": {"skills": "…", "plan": "…"}}
    assert fetched.pdf_path is None

    # GDPR cascade: deleting the user removes their PDP.
    user_row = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    await session.delete(user_row)
    await session.flush()
    session.expire_all()
    assert (await session.execute(select(Pdp).where(Pdp.id == pdp_id))).first() is None


async def test_goal_milestone_task_hierarchy_and_cascade(session: AsyncSession) -> None:
    """Deleting a goal cascades to its milestones and tasks (§5.2 hierarchy, §4 cascade)."""
    user = _make_user()
    session.add(user)
    await session.flush()
    goal = Goal(user_id=user.id, title="Grow into leadership", target_role="Eng Manager")
    session.add(goal)
    await session.flush()
    milestone = Milestone(goal_id=goal.id, title="Mentor two engineers")
    session.add(milestone)
    await session.flush()
    # One task under the milestone, one directly under the goal (no milestone yet).
    task_m = DashboardTask(goal_id=goal.id, milestone_id=milestone.id, title="Weekly 1:1s")
    task_g = DashboardTask(goal_id=goal.id, title="Read leadership book")
    session.add_all([task_m, task_g])
    await session.flush()
    goal_id, milestone_id = goal.id, milestone.id
    task_m_id, task_g_id = task_m.id, task_g.id

    # Delete the goal → its milestones and tasks go with it.
    goal_row = (await session.execute(select(Goal).where(Goal.id == goal_id))).scalar_one()
    await session.delete(goal_row)
    await session.flush()
    session.expire_all()
    assert (
        await session.execute(select(Milestone).where(Milestone.id == milestone_id))
    ).first() is None
    assert (
        await session.execute(
            select(DashboardTask).where(DashboardTask.id.in_([task_m_id, task_g_id]))
        )
    ).first() is None


async def test_deleting_milestone_detaches_tasks(session: AsyncSession) -> None:
    """Deleting a milestone SET-NULLs its tasks' ``milestone_id`` (task survives)."""
    user = _make_user()
    session.add(user)
    await session.flush()
    goal = Goal(user_id=user.id, title="Ship v2")
    session.add(goal)
    await session.flush()
    milestone = Milestone(goal_id=goal.id, title="Beta launch")
    session.add(milestone)
    await session.flush()
    task = DashboardTask(goal_id=goal.id, milestone_id=milestone.id, title="Fix bugs")
    session.add(task)
    await session.flush()
    task_id, milestone_id = task.id, milestone.id

    milestone_row = (
        await session.execute(select(Milestone).where(Milestone.id == milestone_id))
    ).scalar_one()
    await session.delete(milestone_row)
    await session.flush()
    session.expire_all()

    surviving = (
        await session.execute(select(DashboardTask).where(DashboardTask.id == task_id))
    ).scalar_one()
    assert surviving.milestone_id is None  # detached, not deleted


async def test_user_delete_cascades_goals(session: AsyncSession) -> None:
    """A GDPR user-delete removes the user's goals (§4)."""
    user = _make_user()
    session.add(user)
    await session.flush()
    goal = Goal(user_id=user.id, title="Learn Rust")
    session.add(goal)
    await session.flush()
    goal_id, user_id = goal.id, user.id

    user_row = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    await session.delete(user_row)
    await session.flush()
    session.expire_all()
    assert (await session.execute(select(Goal).where(Goal.id == goal_id))).first() is None


async def test_progress_entry_survives_goal_delete_but_not_user_delete(
    session: AsyncSession,
) -> None:
    """progress_entries: ``goal_id`` SET NULL on goal-delete, cascade on user-delete (§4)."""
    user = _make_user()
    session.add(user)
    await session.flush()
    goal = Goal(user_id=user.id, title="Run a marathon")
    session.add(goal)
    await session.flush()
    entry = ProgressEntry(user_id=user.id, goal_id=goal.id, note="Ran 10k today", source="user")
    session.add(entry)
    await session.flush()
    entry_id, goal_id, user_id = entry.id, goal.id, user.id

    # Deleting the goal detaches the log entry (append-only history survives).
    goal_row = (await session.execute(select(Goal).where(Goal.id == goal_id))).scalar_one()
    await session.delete(goal_row)
    await session.flush()
    session.expire_all()
    surviving = (
        await session.execute(select(ProgressEntry).where(ProgressEntry.id == entry_id))
    ).scalar_one()
    assert surviving.goal_id is None

    # Deleting the user erases the log entry.
    user_row = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    await session.delete(user_row)
    await session.flush()
    session.expire_all()
    assert (
        await session.execute(select(ProgressEntry).where(ProgressEntry.id == entry_id))
    ).first() is None


async def test_task_status_check_constraint(session: AsyncSession) -> None:
    """An out-of-vocabulary task ``status`` is rejected by the CHECK constraint."""
    user = _make_user()
    session.add(user)
    await session.flush()
    goal = Goal(user_id=user.id, title="g")
    session.add(goal)
    await session.flush()
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(DashboardTask(goal_id=goal.id, title="t", status="nonsense"))
            await session.flush()


async def test_task_source_check_constraint(session: AsyncSession) -> None:
    """An out-of-vocabulary ``source`` (§5.2 attribution) is rejected by the CHECK."""
    user = _make_user()
    session.add(user)
    await session.flush()
    goal = Goal(user_id=user.id, title="g")
    session.add(goal)
    await session.flush()
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(DashboardTask(goal_id=goal.id, title="t", source="robot"))
            await session.flush()


async def test_task_source_ai_and_proposed_status_allowed(session: AsyncSession) -> None:
    """The AI-proposal posture fits the existing constraints: source='ai', status='proposed'."""
    user = _make_user()
    session.add(user)
    await session.flush()
    goal = Goal(user_id=user.id, title="g", source="ai", status="proposed")
    session.add(goal)
    await session.flush()
    task = DashboardTask(goal_id=goal.id, title="AI-proposed task", source="ai", status="proposed")
    session.add(task)
    await session.flush()
    task_id = task.id
    session.expire_all()
    fetched = (
        await session.execute(select(DashboardTask).where(DashboardTask.id == task_id))
    ).scalar_one()
    assert fetched.source == "ai"
    assert fetched.status == "proposed"
