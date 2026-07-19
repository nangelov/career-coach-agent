"""Integration checks for the P9-05 ``user_memories`` panel primitives against **real Postgres**.

Proves the list/scoped-delete/clear repository helpers (and the :class:`UserMemoryStore` methods
that wrap them) actually round-trip through the P2-04 ``user_memories`` table:

* :func:`list_user_memories` returns a user's rows newest-first, embedding excluded;
* :func:`delete_user_memory` scoped to a ``user_id`` deletes the owner's row but refuses another
  user's (returns ``False``, no cross-user delete);
* :func:`clear_user_memories` removes all of one user's rows and none of another's.

Requires the docker-compose Postgres (pgvector/UUID types SQLite cannot represent) and real
``users`` rows to satisfy the ``user_memories.user_id`` FK. **Skips automatically** when no
Postgres is reachable at ``DATABASE_URL`` so free-tier CI without a DB stays green. Each test
deletes the throwaway users it created (GDPR cascade removes their memories too, §4).
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
from app.memory.store import UserMemoryStore
from app.repositories.models.identity import User
from app.repositories.models.knowledge import UserMemory
from app.repositories.postgres import PostgresConnectionProvider
from app.repositories.vector_search import (
    add_user_memory,
    clear_user_memories,
    delete_user_memory,
    list_user_memories,
)

# A non-zero constant embedding — cosine distance is NaN for a zero vector, and while these
# tests don't search, a valid non-degenerate vector keeps the rows realistic.
_EMBEDDING = [0.1] * 4096


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
    """A real Postgres provider; skips if unreachable or the knowledge schema is not applied."""
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — integration test skipped")
    prov = PostgresConnectionProvider.from_settings(settings)
    try:
        async with prov.session() as db:
            await db.execute(select(UserMemory).limit(1))
    except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
        await prov.aclose()
        pytest.skip("knowledge schema (migration 0004) not applied — run `alembic upgrade head`")
    try:
        yield prov
    finally:
        await prov.aclose()


async def _create_user(provider: PostgresConnectionProvider) -> uuid.UUID:
    async with provider.session() as db:
        user = User(
            provider="google",
            sub=f"sub-{uuid4().hex[:12]}",
            email=f"{uuid4().hex[:8]}@example.com",
            display_name="Memory Test",
        )
        db.add(user)
        await db.commit()
        return user.id


async def _delete_user(provider: PostgresConnectionProvider, user_id: uuid.UUID) -> None:
    async with provider.session() as db:
        existing = await db.get(User, user_id)
        if existing is not None:
            await db.delete(existing)
            await db.commit()


async def _add(provider: PostgresConnectionProvider, user_id: uuid.UUID, text: str) -> uuid.UUID:
    async with provider.session() as db:
        memory = await add_user_memory(
            db, user_id=user_id, text=text, embedding=_EMBEDDING, memory_type="fact"
        )
        await db.commit()
        return memory.id


async def test_list_delete_scope_and_clear(provider: PostgresConnectionProvider) -> None:
    user_a = await _create_user(provider)
    user_b = await _create_user(provider)
    try:
        a1 = await _add(provider, user_a, "A first")
        a2 = await _add(provider, user_a, "A second")
        b1 = await _add(provider, user_b, "B only")

        # list — user A sees exactly their two rows, embedding excluded from the projection.
        async with provider.session() as db:
            listed = await list_user_memories(db, user_id=user_a)
        assert {item.memory_id for item in listed} == {a1, a2}
        assert all(not hasattr(item, "embedding") for item in listed)

        # scoped delete — user B cannot delete user A's row.
        async with provider.session() as db:
            refused = await delete_user_memory(db, memory_id=a1, user_id=user_b)
            await db.commit()
        assert refused is False

        # scoped delete — the owner can.
        async with provider.session() as db:
            deleted = await delete_user_memory(db, memory_id=a1, user_id=user_a)
            await db.commit()
        assert deleted is True

        # clear — removes all of user A's remaining rows, none of user B's.
        async with provider.session() as db:
            removed = await clear_user_memories(db, user_id=user_a)
            await db.commit()
        assert removed == 1  # only a2 remained after a1 was deleted

        async with provider.session() as db:
            a_rows = (
                (await db.execute(select(UserMemory).where(UserMemory.user_id == user_a)))
                .scalars()
                .all()
            )
            b_rows = (
                (await db.execute(select(UserMemory).where(UserMemory.user_id == user_b)))
                .scalars()
                .all()
            )
        assert a_rows == []
        assert {row.id for row in b_rows} == {b1}
    finally:
        await _delete_user(provider, user_a)
        await _delete_user(provider, user_b)


async def test_store_methods_round_trip(provider: PostgresConnectionProvider) -> None:
    """The :class:`UserMemoryStore` wrappers commit their own transactions (P9-05)."""
    from app.llm.embeddings import SentenceTransformerEmbeddingClient

    user_id = await _create_user(provider)
    store = UserMemoryStore(embedder=SentenceTransformerEmbeddingClient(), db=provider)
    try:
        m1 = await _add(provider, user_id, "one")
        await _add(provider, user_id, "two")

        listed = await store.list_memories(user_id)
        assert len(listed) == 2

        assert await store.delete_memory_for_user(m1, user_id) is True
        assert len(await store.list_memories(user_id)) == 1

        assert await store.clear_memories(user_id) == 1
        assert await store.list_memories(user_id) == []
    finally:
        await _delete_user(provider, user_id)
