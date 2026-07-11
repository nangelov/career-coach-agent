"""Integration checks for :class:`PostgresUserStore` against **real Postgres** (P3-02).

Proves the SSO user-upsert adapter actually round-trips through the P2-03 ``users`` table:
a first login inserts a row (returning a stable id), and a return login for the same
``(provider, sub)`` updates the mutable PII while keeping the **same** id (the
``uq_users_provider_sub`` ``ON CONFLICT`` path).

Requires the docker-compose Postgres (JSONB/UUID types SQLite cannot represent). The suite
**skips automatically** when no Postgres is reachable at ``DATABASE_URL`` so free-tier CI
without a DB stays green. Each test deletes the throwaway user it created (GDPR cascade, §4),
leaving the DB as found.
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
from app.repositories.models.identity import User
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
    """A real Postgres provider; skips if unreachable or the 0002 schema is not applied."""
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — integration test skipped")
    prov = PostgresConnectionProvider.from_settings(settings)
    try:
        async with prov.session() as db:
            await db.execute(select(User).limit(1))
    except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
        await prov.aclose()
        pytest.skip("identity schema (migration 0002) not applied — run `alembic upgrade head`")
    try:
        yield prov
    finally:
        await prov.aclose()


async def _delete_user(provider: PostgresConnectionProvider, user_id: str) -> None:
    async with provider.session() as db:
        existing = await db.get(User, uuid.UUID(user_id))
        if existing is not None:
            await db.delete(existing)
            await db.commit()


async def test_upsert_inserts_then_updates_same_row(
    provider: PostgresConnectionProvider,
) -> None:
    store = PostgresUserStore(provider)
    sub = f"sub-{uuid4().hex[:12]}"
    created_id: str | None = None
    try:
        first = await store.upsert(
            provider="google", sub=sub, email="old@example.com", display_name="Old"
        )
        created_id = first.id
        assert first.provider == "google"
        assert first.sub == sub

        second = await store.upsert(
            provider="google", sub=sub, email="new@example.com", display_name="New"
        )
        # Same identity → same durable id; mutable PII refreshed on the existing row.
        assert second.id == first.id
        assert second.email == "new@example.com"
        assert second.display_name == "New"

        # Verify the persisted row reflects the update (no duplicate inserted).
        async with provider.session() as db:
            rows = (
                (await db.execute(select(User).where(User.provider == "google", User.sub == sub)))
                .scalars()
                .all()
            )
        assert len(rows) == 1
        assert rows[0].email == "new@example.com"
    finally:
        if created_id is not None:
            await _delete_user(provider, created_id)
