"""Integration checks for :class:`PostgresProfileStore` against **real Postgres** (P5-05).

Proves the profile get/upsert adapter actually round-trips through the P5-03 ``profiles``
table: ``get`` on a fresh user is ``None``; a first ``upsert`` inserts one row; a second
``upsert`` for the same user replaces its ``data`` in place (the ``ON CONFLICT (user_id)``
path — still exactly one row); and ``get`` reads the stored JSONB back into a
:class:`ProfileSchema`.

Requires the docker-compose Postgres (JSONB/UUID types SQLite cannot represent) and a real
``users`` row to satisfy the ``profiles.user_id`` foreign key. The suite **skips
automatically** when no Postgres is reachable at ``DATABASE_URL`` so free-tier CI without a
DB stays green. Each test deletes the throwaway user it created (GDPR cascade removes the
profile too, §4), leaving the DB as found.
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
from app.ingestion.profile import ProfileSchema
from app.repositories.models.identity import Profile, User
from app.repositories.postgres import PostgresConnectionProvider
from app.repositories.profile_store import PostgresProfileStore


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
    """A real Postgres provider; skips if unreachable or the identity schema is not applied."""
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — integration test skipped")
    prov = PostgresConnectionProvider.from_settings(settings)
    try:
        async with prov.session() as db:
            await db.execute(select(Profile).limit(1))
    except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
        await prov.aclose()
        pytest.skip("identity schema (migration 0002) not applied — run `alembic upgrade head`")
    try:
        yield prov
    finally:
        await prov.aclose()


async def _create_user(provider: PostgresConnectionProvider) -> str:
    """Insert a throwaway user (the profile FK anchor) and return its id."""
    async with provider.session() as db:
        user = User(
            provider="google",
            sub=f"sub-{uuid4().hex[:12]}",
            email=f"{uuid4().hex[:8]}@example.com",
            display_name="Profile Test",
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


async def test_get_none_then_upsert_inserts_then_updates(
    provider: PostgresConnectionProvider,
) -> None:
    store = PostgresProfileStore(provider)
    user_id = await _create_user(provider)
    try:
        # No profile yet → None (distinct from an empty profile).
        assert await store.get(user_id) is None

        # First upsert inserts one row.
        created = await store.upsert(
            user_id, ProfileSchema(skills=["Python"], goals=["Staff engineer"])
        )
        assert created.skills == ["Python"]
        fetched = await store.get(user_id)
        assert fetched is not None
        assert fetched.skills == ["Python"]
        assert fetched.goals == ["Staff engineer"]

        # Second upsert replaces data in place — still exactly one row.
        await store.upsert(user_id, ProfileSchema(skills=["Rust"]))
        updated = await store.get(user_id)
        assert updated is not None
        assert updated.skills == ["Rust"]
        assert updated.goals == []

        async with provider.session() as db:
            rows = (
                (await db.execute(select(Profile).where(Profile.user_id == uuid.UUID(user_id))))
                .scalars()
                .all()
            )
        assert len(rows) == 1
    finally:
        await _delete_user(provider, user_id)


async def test_get_malformed_user_id_returns_none(
    provider: PostgresConnectionProvider,
) -> None:
    store = PostgresProfileStore(provider)
    # A non-UUID id fails safe as "no profile" rather than raising.
    assert await store.get("not-a-uuid") is None
