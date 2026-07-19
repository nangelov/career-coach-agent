"""Live-Postgres integration test for the retention purge (S14, §6.18 / §7.6).

Proves against the **real** schema (JSONB / UUID / ``vector(4096)`` FKs SQLite cannot represent)
that:

* :class:`~app.repositories.retention.PostgresRetentionRepository` correctly derives "last
  activity" (``MAX(messages.created_at)`` falling back to ``users.created_at``), including the
  strict-``<`` boundary and the never-chatted fallback; and
* the full :func:`~app.tasks.retention_purge.run_retention_purge` core, wired to that finder and
  the **real** :meth:`~app.repositories.account.PostgresAccountRepository.delete_user` cascade,
  erases a stale user's **entire** footprint (conversation/message, profile, preference, memory,
  dashboard rows) while a fresh user's data survives.

Skips cleanly when no Postgres / the schema is unreachable, matching the P2/P5/P9 live-DB
convention. Every throwaway user is deleted at the end (the same cascade under test), leaving the
DB as found.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.repositories.account import PostgresAccountRepository
from app.repositories.models.dashboard import DashboardTask, Goal, Milestone, Pdp, ProgressEntry
from app.repositories.models.identity import (
    Conversation,
    Message,
    Preference,
    Profile,
    Session,
    User,
)
from app.repositories.models.knowledge import EMBEDDING_DIM, UserMemory
from app.repositories.postgres import PostgresConnectionProvider
from app.repositories.retention import PostgresRetentionRepository
from app.tasks.retention_purge import run_retention_purge

_EMBED = [0.1] * EMBEDDING_DIM
_NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


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
            await db.execute(select(UserMemory).limit(1))
    except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
        await prov.aclose()
        pytest.skip("schema (migrations) not applied — run `alembic upgrade head`")
    try:
        yield prov
    finally:
        await prov.aclose()


async def _seed_user(
    provider: PostgresConnectionProvider,
    *,
    created_at: datetime,
    last_message_at: datetime | None,
    full_footprint: bool = False,
) -> str:
    """Insert a user with an explicit ``created_at`` and (optionally) a message at a set time.

    ``last_message_at=None`` → a never-chatted user (last activity = ``created_at``). When
    ``full_footprint`` is set, also seed profile/preference/memory/dashboard rows so the cascade
    can be proven.
    """
    async with provider.session() as db:
        user = User(
            provider="google",
            sub=f"sub-{uuid4().hex[:12]}",
            email=f"{uuid4().hex[:8]}@example.com",
            display_name="Retention",
            created_at=created_at,
        )
        db.add(user)
        await db.flush()
        uid = user.id

        if last_message_at is not None:
            session_id = uuid4().hex
            db.add(Session(id=session_id, user_id=uid))
            conversation = Conversation(session_id=session_id, user_id=uid, title="Chat")
            db.add(conversation)
            await db.flush()
            db.add(
                Message(
                    conversation_id=conversation.id,
                    message_id=uuid4().hex,
                    role="user",
                    content="Hello",
                    created_at=last_message_at,
                )
            )

        if full_footprint:
            db.add(Profile(user_id=uid, data={"skills": ["Python"]}))
            db.add(Preference(user_id=uid, data={"tone": "concise"}))
            db.add(
                UserMemory(
                    user_id=uid, text="Prefers Python", embedding=_EMBED, memory_type="preference"
                )
            )
            db.add(Pdp(user_id=uid, career_goal="Staff engineer"))
            goal = Goal(user_id=uid, title="Grow", status="active", source="user")
            db.add(goal)
            await db.flush()
            milestone = Milestone(goal_id=goal.id, title="M1", status="pending", source="user")
            db.add(milestone)
            await db.flush()
            db.add(
                DashboardTask(
                    goal_id=goal.id,
                    milestone_id=milestone.id,
                    title="T1",
                    status="todo",
                    source="user",
                )
            )
            db.add(ProgressEntry(user_id=uid, goal_id=goal.id, note="did it", source="user"))

        await db.commit()
        return str(uid)


async def _delete_user(provider: PostgresConnectionProvider, user_id: str) -> None:
    async with provider.session() as db:
        existing = await db.get(User, uuid.UUID(user_id))
        if existing is not None:
            await db.delete(existing)
            await db.commit()


async def test_stale_user_ids_uses_last_message_with_created_at_fallback(
    provider: PostgresConnectionProvider,
) -> None:
    repo = PostgresRetentionRepository(provider)
    # Chatted long ago → stale (last activity = the old message).
    chatted_stale = await _seed_user(
        provider, created_at=_NOW - timedelta(days=200), last_message_at=_NOW - timedelta(days=40)
    )
    # Chatted recently → fresh (even though the account is old).
    chatted_fresh = await _seed_user(
        provider, created_at=_NOW - timedelta(days=200), last_message_at=_NOW - timedelta(days=5)
    )
    # Never chatted, old account → stale via created_at fallback.
    never_stale = await _seed_user(
        provider, created_at=_NOW - timedelta(days=40), last_message_at=None
    )
    # Never chatted, new account → fresh.
    never_fresh = await _seed_user(
        provider, created_at=_NOW - timedelta(days=5), last_message_at=None
    )
    # Exactly at the cutoff → strict ``<`` excludes it (not yet stale).
    boundary = await _seed_user(
        provider, created_at=_NOW - timedelta(days=200), last_message_at=_NOW - timedelta(days=30)
    )
    created = [chatted_stale, chatted_fresh, never_stale, never_fresh, boundary]
    try:
        cutoff = _NOW - timedelta(days=30)
        stale = set(await repo.stale_user_ids(older_than=cutoff))

        assert chatted_stale in stale
        assert never_stale in stale
        assert chatted_fresh not in stale
        assert never_fresh not in stale
        assert boundary not in stale  # last activity == cutoff → strict < excludes
    finally:
        for uid in created:
            await _delete_user(provider, uid)


async def test_purge_erases_stale_footprint_and_spares_fresh(
    provider: PostgresConnectionProvider,
) -> None:
    stale = await _seed_user(
        provider,
        created_at=_NOW - timedelta(days=200),
        last_message_at=_NOW - timedelta(days=45),
        full_footprint=True,
    )
    fresh = await _seed_user(
        provider,
        created_at=_NOW - timedelta(days=200),
        last_message_at=_NOW - timedelta(days=3),
        full_footprint=True,
    )
    stale_uid = uuid.UUID(stale)
    fresh_uid = uuid.UUID(fresh)
    try:
        result = await run_retention_purge(
            finder=PostgresRetentionRepository.from_provider(provider),
            eraser=PostgresAccountRepository.from_provider(provider),
            retention_days=30,
            now=_NOW,
        )
        # The sweep purges at least our stale user (other stale rows may exist in a shared DB).
        assert result["purged"] >= 1
        assert result["failed"] == 0

        async with provider.session() as db:

            async def _count(model: object, uid: uuid.UUID) -> int:
                return (
                    await db.execute(
                        select(func.count()).select_from(model).where(model.user_id == uid)  # type: ignore[attr-defined]
                    )
                ).scalar_one()

            # Stale user: whole footprint gone via the cascade.
            assert await db.get(User, stale_uid) is None
            assert await _count(Profile, stale_uid) == 0
            assert await _count(Preference, stale_uid) == 0
            assert await _count(UserMemory, stale_uid) == 0
            assert await _count(Conversation, stale_uid) == 0
            assert await _count(Pdp, stale_uid) == 0
            assert await _count(Goal, stale_uid) == 0
            assert await _count(ProgressEntry, stale_uid) == 0
            assert (
                await db.execute(
                    select(func.count())
                    .select_from(Message)
                    .join(Conversation, Message.conversation_id == Conversation.id)
                    .where(Conversation.user_id == stale_uid)
                )
            ).scalar_one() == 0

            # Fresh user: fully intact.
            assert await db.get(User, fresh_uid) is not None
            assert await _count(Profile, fresh_uid) == 1
            assert await _count(UserMemory, fresh_uid) == 1
            assert await _count(Conversation, fresh_uid) == 1
    finally:
        await _delete_user(provider, stale)
        await _delete_user(provider, fresh)
