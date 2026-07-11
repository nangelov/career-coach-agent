"""Integration checks for admin authz + feedback read against **real Postgres** (P3-05).

Proves the two DB-facing pieces of P3-05 round-trip through the real schema:

* :meth:`PostgresUserStore.is_admin` reads the new ``users.is_admin`` flag (migration 0005) —
  ``false`` for a fresh user, ``true`` after the row is flagged, ``false`` for an unknown id;
* :meth:`PostgresFeedbackReader.list_feedback` returns stored ``feedback`` rows newest-first.

Requires the docker-compose Postgres with migrations applied (``alembic upgrade head``). The
suite **skips automatically** when Postgres is unreachable or the ``is_admin`` column is not
yet present, so free-tier CI without a DB stays green. Each test cleans up the throwaway rows
it created, leaving the DB as found.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.repositories.feedback_store import PostgresFeedbackReader
from app.repositories.models.identity import Feedback, User
from app.repositories.postgres import PostgresConnectionProvider
from app.repositories.user_store import PostgresUserStore


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
    """A real Postgres provider; skips if unreachable or the is_admin column is missing."""
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — integration test skipped")
    prov = PostgresConnectionProvider.from_settings(settings)
    try:
        # Selecting the ORM (which now maps ``is_admin``) fails if migration 0005 is unapplied.
        async with prov.session() as db:
            await db.execute(select(User).limit(1))
    except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
        await prov.aclose()
        pytest.skip("admin schema (migration 0005) not applied — run `alembic upgrade head`")
    try:
        yield prov
    finally:
        await prov.aclose()


async def test_is_admin_flag_roundtrips(provider: PostgresConnectionProvider) -> None:
    store = PostgresUserStore(provider)
    sub = f"sub-{uuid4().hex[:12]}"
    account = await store.upsert(
        provider="google", sub=sub, email=f"{sub}@example.com", display_name="Admin Candidate"
    )
    try:
        # Fresh user defaults to non-admin.
        assert await store.is_admin(account.id) is False
        # Unknown id → fail-closed.
        assert await store.is_admin(uuid4().hex) is False
        # Grant admin out-of-band (as an operator would via SQL), then re-check.
        async with provider.session() as db:
            await db.execute(
                update(User).where(User.id == uuid.UUID(account.id)).values(is_admin=True)
            )
            await db.commit()
        assert await store.is_admin(account.id) is True
    finally:
        async with provider.session() as db:
            existing = await db.get(User, uuid.UUID(account.id))
            if existing is not None:
                await db.delete(existing)
                await db.commit()


async def test_list_feedback_newest_first(provider: PostgresConnectionProvider) -> None:
    reader = PostgresFeedbackReader(provider)
    marker = f"p3-05-{uuid4().hex[:8]}"
    ids: list[uuid.UUID] = []
    try:
        # Explicit, distinct timestamps: rows written in one transaction all share the same
        # ``now()`` default, so give each a spaced ``created_at`` to test newest-first
        # ordering deterministically (#2 is the newest).
        base = datetime.now(UTC)
        async with provider.session() as db:
            for i in range(3):
                row = Feedback(content=f"{marker} #{i}", created_at=base + timedelta(seconds=i))
                db.add(row)
                await db.flush()
                ids.append(row.id)
            await db.commit()

        entries = await reader.list_feedback(limit=1000)
        ours = [e for e in entries if e.content.startswith(marker)]
        assert len(ours) == 3
        # Newest first: #2 has the latest created_at, so it leads the marker subset.
        assert ours[0].content.endswith("#2")
        assert ours[-1].content.endswith("#0")
        # Overall ordering is non-increasing by created_at.
        times = [e.created_at for e in entries]
        assert times == sorted(times, reverse=True)
    finally:
        async with provider.session() as db:
            await db.execute(delete(Feedback).where(Feedback.id.in_(ids)))
            await db.commit()
