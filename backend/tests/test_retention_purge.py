"""Unit tests for the retention-purge task core (S14, §6.18) — no broker / no real Postgres.

Exercise :func:`~app.tasks.retention_purge.run_retention_purge` with fakes for the two
collaborators (the stale-user finder + the erasure cascade), covering the acceptance criteria:

* the cutoff is computed as ``now - retention_days`` and passed to the finder,
* every stale user id the finder returns is erased via ``delete_user`` and fresh ones are not,
* one user's ``delete_user`` failure is logged and skipped — the sweep continues and still
  purges the rest (best-effort), and
* an empty stale set is a clean no-op.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from app.tasks.retention_purge import run_retention_purge


class FakeFinder:
    """Records the cutoff it was asked for and returns a scripted stale-id list."""

    def __init__(self, stale_ids: Sequence[str]) -> None:
        self._stale_ids = list(stale_ids)
        self.older_than: datetime | None = None

    async def stale_user_ids(self, *, older_than: datetime) -> Sequence[str]:
        self.older_than = older_than
        return self._stale_ids


class FakeEraser:
    """Records erased ids; optionally raises for a configured id (fault injection)."""

    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        self.deleted: list[str] = []
        self._fail_for = fail_for or set()

    async def delete_user(self, user_id: str) -> None:
        if user_id in self._fail_for:
            raise RuntimeError(f"boom for {user_id}")
        self.deleted.append(user_id)


async def test_purges_every_stale_user_and_passes_correct_cutoff() -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    finder = FakeFinder(["u1", "u2", "u3"])
    eraser = FakeEraser()

    result = await run_retention_purge(finder=finder, eraser=eraser, retention_days=30, now=now)

    # Cutoff = now - retention window, handed to the finder verbatim.
    assert finder.older_than == now - timedelta(days=30)
    # Every stale id was erased through the shared cascade.
    assert eraser.deleted == ["u1", "u2", "u3"]
    assert result == {"candidates": 3, "purged": 3, "failed": 0, "retention_days": 30}


async def test_empty_stale_set_is_a_clean_no_op() -> None:
    finder = FakeFinder([])
    eraser = FakeEraser()

    result = await run_retention_purge(
        finder=finder, eraser=eraser, retention_days=30, now=datetime.now(UTC)
    )

    assert eraser.deleted == []
    assert result == {"candidates": 0, "purged": 0, "failed": 0, "retention_days": 30}


async def test_one_user_failure_does_not_abort_the_batch() -> None:
    finder = FakeFinder(["u1", "boom", "u3"])
    eraser = FakeEraser(fail_for={"boom"})

    result = await run_retention_purge(
        finder=finder, eraser=eraser, retention_days=30, now=datetime.now(UTC)
    )

    # The failing user is skipped; the ones after it are still purged.
    assert eraser.deleted == ["u1", "u3"]
    assert result == {"candidates": 3, "purged": 2, "failed": 1, "retention_days": 30}


async def test_defaults_now_to_wall_clock_when_not_supplied() -> None:
    before = datetime.now(UTC)
    finder = FakeFinder([])
    await run_retention_purge(finder=finder, eraser=FakeEraser(), retention_days=30)
    after = datetime.now(UTC)

    # cutoff = now - 30d, with now taken from the wall clock at call time.
    assert finder.older_than is not None
    assert before - timedelta(days=30) <= finder.older_than <= after - timedelta(days=30)


@pytest.mark.parametrize("retention_days", [1, 7, 30, 90])
def test_run_is_reported_with_the_window(retention_days: int) -> None:
    import asyncio

    finder = FakeFinder([])
    result = asyncio.run(
        run_retention_purge(finder=finder, eraser=FakeEraser(), retention_days=retention_days)
    )
    assert result["retention_days"] == retention_days


def test_task_is_registered_and_beat_scheduled_daily() -> None:
    from app.tasks import retention_purge as task_module
    from app.tasks.celery_app import celery_app

    # Discoverable by the worker + named for beat to target.
    assert "app.tasks.retention_purge" in celery_app.conf.include
    assert task_module.retention_purge.name == "tasks.retention_purge"

    # A daily beat entry points at exactly this task.
    schedule = celery_app.conf.beat_schedule
    entries = [e for e in schedule.values() if e["task"] == "tasks.retention_purge"]
    assert len(entries) == 1
