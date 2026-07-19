"""Periodic retention-purge Celery task — erase SSO users inactive > N days (S14, §6.18).

Deletes an SSO user's **entire** durable footprint (conversations, CVs/profiles, learned
memories, preferences, PDPs/dashboard) once they have been inactive for longer than the
configured retention window (``RETENTION_PURGE_AFTER_DAYS``, default 30 — §6.18 *"Retention →
SSO users: 1 month"*). Guests need no purge job: their data is Redis-only and dies with the
session TTL (P3-01 / P9-07).

**One cascading-delete path, reused — not re-implemented.** The purge does not hand-write any
per-table deletes: it feeds each stale user id back through the existing
:meth:`~app.repositories.account.PostgresAccountRepository.delete_user` cascade — the very same
SEC-05 / Art. 17 erasure that ``DELETE /api/me`` uses. The purge is simply *that erasure,
triggered by inactivity instead of the user's own request*. "Which users are stale?" is the
only new query, owned by :class:`~app.repositories.retention.PostgresRetentionRepository`.

**No admin carve-out.** ``is_admin`` is a plain app-level flag on the same ``users`` row; the
retention design (§6 item 26 / §6.18) names no admin data-retention exception, so the purge
applies **uniformly** — an admin who goes inactive for the window is purged like anyone else.
This is a deliberate reading, not an oversight.

**Best-effort per user.** One user's ``delete_user`` failure is logged and the sweep continues
with the rest (a single bad row must not strand every other stale account); the task returns a
count of purged / failed / candidate users.

**Traces (OTel) are out of scope here.** OpenTelemetry export + its retention live in P11 (not
yet built). Most OTel backends carry their **own** retention setting, so P11's trace store will
configure retention there; this task owns the Postgres/Redis footprint, which is what exists
today. Redis session records for a long-inactive user have already self-expired on their TTL,
so there is nothing Redis-side to purge here.

**Sync task, async stack — the bridge (mirrors :mod:`app.tasks.profile_ingest`).** Celery tasks
are synchronous but the DB stack is async-only, so the task wraps an async core in
:func:`asyncio.run` and constructs its **own** Postgres provider inside the worker process (a
worker does not share the FastAPI ``app.state``), disposing it when the run ends. Heavy imports
are deferred so importing this module (for the Celery ``include`` list / beat schedule) stays
light.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from app.config import settings
from app.tasks.celery_app import celery_app

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Injected-collaborator ports (structural — real impls satisfy them; tests fake them)
# --------------------------------------------------------------------------- #
class StaleUserFinder(Protocol):
    """The read-only "who is stale?" query (real PostgresRetentionRepository)."""

    async def stale_user_ids(self, *, older_than: datetime) -> Sequence[str]: ...


class UserEraser(Protocol):
    """The cascading erasure primitive (real PostgresAccountRepository.delete_user)."""

    async def delete_user(self, user_id: str) -> None: ...


async def run_retention_purge(
    *,
    finder: StaleUserFinder,
    eraser: UserEraser,
    retention_days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Purge every SSO user inactive for longer than ``retention_days``; return a summary.

    The **injected**, testable core of the task (no Celery/broker/real Postgres required): the
    finder and eraser are passed in so a unit test drives it with fakes. Computes the cutoff as
    ``now - retention_days``, asks the finder for stale user ids, and erases each via the shared
    cascade. A single user's delete failure is logged and skipped (the sweep continues).

    Returns a JSON-serializable dict — the Celery task result: ``{"candidates", "purged",
    "failed", "retention_days"}``.
    """
    reference = now if now is not None else datetime.now(UTC)
    cutoff = reference - timedelta(days=retention_days)
    user_ids = list(await finder.stale_user_ids(older_than=cutoff))

    purged = 0
    failed = 0
    for user_id in user_ids:
        try:
            await eraser.delete_user(user_id)
            purged += 1
        except Exception:  # noqa: BLE001 - best-effort sweep: log + continue, never abort the run
            failed += 1
            logger.warning("retention purge failed for user %s", user_id, exc_info=True)

    logger.info(
        "retention purge complete: %d candidate(s), %d purged, %d failed (window=%dd)",
        len(user_ids),
        purged,
        failed,
        retention_days,
    )
    return {
        "candidates": len(user_ids),
        "purged": purged,
        "failed": failed,
        "retention_days": retention_days,
    }


async def _purge_entrypoint(*, retention_days: int) -> dict[str, Any]:
    """Build the worker-local collaborators, run the purge, and release resources.

    The standalone-worker composition root for the purge: constructs its own Postgres provider
    (heavy import deferred), wires the retention finder + the account-erasure cascade over it,
    and disposes the Postgres pool when the run ends.
    """
    from app.repositories.account import PostgresAccountRepository  # noqa: PLC0415
    from app.repositories.postgres import PostgresConnectionProvider  # noqa: PLC0415
    from app.repositories.retention import PostgresRetentionRepository  # noqa: PLC0415

    db: PostgresConnectionProvider | None = None
    try:
        db = PostgresConnectionProvider.from_settings()
        return await run_retention_purge(
            finder=PostgresRetentionRepository.from_provider(db),
            eraser=PostgresAccountRepository.from_provider(db),
            retention_days=retention_days,
        )
    finally:
        if db is not None:
            await db.aclose()


@celery_app.task(name="tasks.retention_purge")
def retention_purge() -> dict[str, Any]:
    """Celery entry (beat-scheduled daily): erase SSO users inactive > the window (§6.18).

    Sync task body bridging to the async core via :func:`asyncio.run`, reading the retention
    window from settings. An unrecoverable error (e.g. the DB is down) propagates so Celery
    records ``FAILURE`` — the next daily run retries the whole sweep, so no state is lost.
    """
    try:
        return asyncio.run(_purge_entrypoint(retention_days=settings.RETENTION_PURGE_AFTER_DAYS))
    except Exception:
        logger.warning("retention purge sweep failed", exc_info=True)
        raise
