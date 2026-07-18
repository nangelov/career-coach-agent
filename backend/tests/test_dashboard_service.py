"""Unit tests for :class:`DashboardService` against the in-memory store (P8-02, §5.2).

Exercises the policy layer without a DB: attribution resolution (user vs AI-proposed), the
approve/reject-via-edit semantics, cross-user isolation, the cascade/detach rules, and the summary
aggregation (time %, task completion %, streak). The pure date helpers are tested directly.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.schemas.dashboard import (
    GoalCreate,
    GoalUpdate,
    MilestoneCreate,
    ProgressEntryCreate,
    TaskCreate,
    TaskUpdate,
)
from app.services.dashboard import (
    DashboardService,
    _current_streak,
    _task_completion_pct,
    _time_progress_pct,
)
from app.services.dashboard_store import InMemoryDashboardStore


def _service() -> DashboardService:
    return DashboardService(InMemoryDashboardStore())


# --------------------------------------------------------------------- attribution
async def test_user_goal_defaults_active_source_user() -> None:
    svc = _service()
    goal = await svc.create_goal("u1", GoalCreate(title="Become a Staff Engineer"))
    assert goal.status == "active"
    assert goal.source == "user"


async def test_ai_goal_defaults_proposed_source_ai() -> None:
    svc = _service()
    goal = await svc.create_goal("u1", GoalCreate(title="AI idea"), source="ai")
    assert goal.status == "proposed"
    assert goal.source == "ai"


async def test_ai_milestone_and_task_default_proposed() -> None:
    svc = _service()
    goal = await svc.create_goal("u1", GoalCreate(title="G"), source="ai")
    milestone = await svc.create_milestone("u1", goal.id, MilestoneCreate(title="M"), source="ai")
    task = await svc.create_task("u1", TaskCreate(goal_id=goal.id, title="T"), source="ai")
    assert milestone is not None and milestone.status == "proposed"
    assert task is not None and task.status == "proposed"


# ------------------------------------------------------------------ approve / reject
async def test_approve_is_status_edit_of_proposed_goal() -> None:
    svc = _service()
    goal = await svc.create_goal("u1", GoalCreate(title="G"), source="ai")
    approved = await svc.update_goal("u1", goal.id, GoalUpdate(status="active"))
    assert approved is not None
    assert approved.status == "active"
    # Source (creation attribution) is unchanged by an approve.
    assert approved.source == "ai"


async def test_reject_is_delete_of_proposed_goal() -> None:
    svc = _service()
    goal = await svc.create_goal("u1", GoalCreate(title="G"), source="ai")
    assert await svc.delete_goal("u1", goal.id) is True
    assert await svc.get_goal("u1", goal.id) is None


# --------------------------------------------------------------- cross-user isolation
async def test_cross_user_goal_access_denied() -> None:
    svc = _service()
    goal = await svc.create_goal("A", GoalCreate(title="A-secret"))
    # B can neither read, edit, nor delete A's goal.
    assert await svc.get_goal("B", goal.id) is None
    assert await svc.update_goal("B", goal.id, GoalUpdate(title="hijack")) is None
    assert await svc.delete_goal("B", goal.id) is False
    assert await svc.list_goals("B") == []
    # A's goal is untouched.
    still = await svc.get_goal("A", goal.id)
    assert still is not None and still.title == "A-secret"


async def test_cross_user_milestone_and_task_denied() -> None:
    svc = _service()
    goal = await svc.create_goal("A", GoalCreate(title="G"))
    milestone = await svc.create_milestone("A", goal.id, MilestoneCreate(title="M"))
    assert milestone is not None
    # B cannot create a milestone under A's goal, nor read A's milestone.
    assert await svc.create_milestone("B", goal.id, MilestoneCreate(title="X")) is None
    assert await svc.get_milestone("B", milestone.id) is None
    assert await svc.list_milestones("B", goal.id) is None
    # B cannot create a task under A's goal.
    assert await svc.create_task("B", TaskCreate(goal_id=goal.id, title="X")) is None


# --------------------------------------------------------------- cascade / detach
async def test_delete_goal_cascades_milestones_and_tasks() -> None:
    svc = _service()
    goal = await svc.create_goal("u1", GoalCreate(title="G"))
    await svc.create_milestone("u1", goal.id, MilestoneCreate(title="M"))
    await svc.create_task("u1", TaskCreate(goal_id=goal.id, title="T"))
    assert await svc.delete_goal("u1", goal.id) is True
    assert await svc.list_tasks("u1") == []
    assert await svc.list_milestones("u1", goal.id) is None  # goal itself gone


async def test_delete_milestone_detaches_its_tasks() -> None:
    svc = _service()
    goal = await svc.create_goal("u1", GoalCreate(title="G"))
    milestone = await svc.create_milestone("u1", goal.id, MilestoneCreate(title="M"))
    assert milestone is not None
    task = await svc.create_task(
        "u1", TaskCreate(goal_id=goal.id, milestone_id=milestone.id, title="T")
    )
    assert task is not None
    assert await svc.delete_milestone("u1", milestone.id) is True
    # The task survives under the goal, detached (milestone_id set to None).
    surviving = await svc.get_task("u1", task.id)
    assert surviving is not None
    assert surviving.milestone_id is None


async def test_task_milestone_must_be_under_same_goal() -> None:
    svc = _service()
    goal_a = await svc.create_goal("u1", GoalCreate(title="A"))
    goal_b = await svc.create_goal("u1", GoalCreate(title="B"))
    milestone_b = await svc.create_milestone("u1", goal_b.id, MilestoneCreate(title="MB"))
    assert milestone_b is not None
    # A task on goal A cannot reference a milestone that belongs to goal B.
    assert (
        await svc.create_task(
            "u1", TaskCreate(goal_id=goal_a.id, milestone_id=milestone_b.id, title="T")
        )
        is None
    )


async def test_update_task_repoint_milestone_cross_goal_denied() -> None:
    svc = _service()
    goal_a = await svc.create_goal("u1", GoalCreate(title="A"))
    goal_b = await svc.create_goal("u1", GoalCreate(title="B"))
    milestone_b = await svc.create_milestone("u1", goal_b.id, MilestoneCreate(title="MB"))
    assert milestone_b is not None
    task = await svc.create_task("u1", TaskCreate(goal_id=goal_a.id, title="T"))
    assert task is not None
    assert await svc.update_task("u1", task.id, TaskUpdate(milestone_id=milestone_b.id)) is None


# ------------------------------------------------------------------------- progress
async def test_progress_append_and_bad_reference_denied() -> None:
    svc = _service()
    goal = await svc.create_goal("u1", GoalCreate(title="G"))
    entry = await svc.add_progress("u1", ProgressEntryCreate(goal_id=goal.id, note="did work"))
    assert entry is not None
    assert entry.source == "user"
    # Referencing someone else's goal is rejected.
    other = await svc.create_goal("u2", GoalCreate(title="theirs"))
    assert await svc.add_progress("u1", ProgressEntryCreate(goal_id=other.id)) is None


async def test_progress_pagination() -> None:
    svc = _service()
    for i in range(5):
        await svc.add_progress("u1", ProgressEntryCreate(note=f"n{i}"))
    page = await svc.list_progress("u1", limit=2, offset=0)
    assert len(page) == 2


# -------------------------------------------------------------------------- summary
async def test_summary_nests_and_aggregates() -> None:
    svc = _service()
    goal = await svc.create_goal("u1", GoalCreate(title="G"))
    await svc.create_milestone("u1", goal.id, MilestoneCreate(title="M"))
    t1 = await svc.create_task("u1", TaskCreate(goal_id=goal.id, title="T1"))
    await svc.create_task("u1", TaskCreate(goal_id=goal.id, title="T2"))
    assert t1 is not None
    await svc.update_task("u1", t1.id, TaskUpdate(status="done"))
    await svc.add_progress("u1", ProgressEntryCreate(note="today"))

    summary = await svc.get_summary("u1")
    assert len(summary.goals) == 1
    g = summary.goals[0]
    assert len(g.milestones) == 1
    assert len(g.tasks) == 2
    assert g.time_progress_pct is None  # no target_date
    assert g.task_completion_pct == 50.0  # 1 of 2 done
    assert summary.progress.total_entries == 1
    assert summary.progress.current_streak_days == 1


async def test_summary_excludes_other_users() -> None:
    svc = _service()
    await svc.create_goal("u1", GoalCreate(title="mine"))
    await svc.create_goal("u2", GoalCreate(title="theirs"))
    summary = await svc.get_summary("u1")
    assert [g.title for g in summary.goals] == ["mine"]


# --------------------------------------------------------------------- date helpers
def test_time_progress_pct() -> None:
    created = date(2026, 1, 1)
    assert _time_progress_pct(created, None, date(2026, 6, 1)) is None
    # Halfway through a 100-day span.
    assert _time_progress_pct(created, date(2026, 1, 11), date(2026, 1, 6)) == 50.0
    # Past the target clamps to 100.
    assert _time_progress_pct(created, date(2026, 1, 11), date(2026, 2, 1)) == 100.0
    # Before start clamps to 0.
    assert _time_progress_pct(created, date(2026, 1, 11), date(2025, 12, 1)) == 0.0
    # Degenerate span (target <= created) is treated complete.
    assert _time_progress_pct(created, created, date(2026, 1, 1)) == 100.0


def test_task_completion_pct_none_when_no_tasks() -> None:
    assert _task_completion_pct([]) is None


@pytest.mark.parametrize(
    ("offsets", "expected"),
    [
        ([], 0),
        ([0], 1),  # today only
        ([1], 1),  # yesterday only (not yet logged today, streak still alive)
        ([0, 1, 2], 3),  # three consecutive days ending today
        ([0, 2], 1),  # gap at day 1 breaks the streak
        ([3, 4], 0),  # most recent activity is 3 days ago — broken
    ],
)
def test_current_streak(offsets: list[int], expected: int) -> None:
    today = datetime.now(UTC).date()
    days = {today - timedelta(days=o) for o in offsets}
    assert _current_streak(days, today) == expected
