"""Integration checks for :class:`PostgresMessageFeedbackStore` against **real Postgres** (P9-01).

Proves the per-message feedback adapter actually writes to and reads from the P2-03
``message_feedback`` table with real ownership enforcement over ``messages`` → ``conversations``:
a user can rate their own message, a resubmission replaces the same row (the migration-0009
unique constraint), a foreign user / wrong guest session is rejected, an unknown message is
rejected, a guest can rate a session-owned message, and ``list_recent_downvotes`` returns a
user's thumbs-down newest-first.

Requires the docker-compose Postgres with migrations applied (JSONB/UUID + the ``message_feedback``
unique constraint SQLite cannot represent). The suite **skips automatically** when no Postgres is
reachable at ``DATABASE_URL`` so free-tier CI without a DB stays green. It creates a throwaway user
and **deletes it at the end**, which cascades away every session/conversation/message/feedback it
created (GDPR cascade, §4), leaving the DB as found.
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
from app.repositories.message_feedback_store import PostgresMessageFeedbackStore
from app.repositories.models.identity import Conversation, Message, Session, User
from app.repositories.postgres import PostgresConnectionProvider


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
            await db.execute(select(User).limit(1))
    except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
        await prov.aclose()
        pytest.skip("identity schema not applied — run `alembic upgrade head`")
    try:
        yield prov
    finally:
        await prov.aclose()


class _Fixture:
    """Ids of a seeded user/session/conversation/message tree for a test."""

    def __init__(self, user_id: str, session_id: str, message_id: str) -> None:
        self.user_id = user_id
        self.session_id = session_id
        self.message_id = message_id


@pytest_asyncio.fixture
async def owned(provider: PostgresConnectionProvider) -> AsyncIterator[_Fixture]:
    """Seed a user → session → conversation → assistant message; delete the user at the end."""
    unique = uuid4().hex[:12]
    session_id = str(uuid.uuid4())
    message_id = uuid4().hex
    async with provider.session() as db:
        user = User(provider="google", sub=f"sub-{unique}", email=f"u-{unique}@example.com")
        db.add(user)
        await db.flush()
        db.add(Session(id=session_id, user_id=user.id))
        conversation = Conversation(session_id=session_id, user_id=user.id)
        db.add(conversation)
        await db.flush()
        db.add(
            Message(
                conversation_id=conversation.id,
                message_id=message_id,
                role="assistant",
                content="Learn Python.",
            )
        )
        uid = str(user.id)
        await db.commit()
    try:
        yield _Fixture(uid, session_id, message_id)
    finally:
        async with provider.session() as db:
            existing = await db.get(User, uuid.UUID(uid))
            if existing is not None:
                await db.delete(existing)
                await db.commit()


async def test_record_and_resubmit_is_idempotent(
    provider: PostgresConnectionProvider, owned: _Fixture
) -> None:
    store = PostgresMessageFeedbackStore(provider)

    first = await store.record(
        message_id=owned.message_id,
        rating="up",
        reason=None,
        user_id=owned.user_id,
        session_id=owned.session_id,
    )
    assert first is not None and first.rating == "up"

    # Resubmit → same row updated, not a duplicate.
    second = await store.record(
        message_id=owned.message_id,
        rating="down",
        reason="not helpful",
        user_id=owned.user_id,
        session_id=owned.session_id,
    )
    assert second is not None and second.rating == "down" and second.reason == "not helpful"

    stored = await store.get_for_message(owned.message_id)
    assert stored is not None and stored.rating == "down"
    downvotes = await store.list_recent_downvotes(owned.user_id, limit=10)
    assert [d.message_id for d in downvotes] == [owned.message_id]


async def test_foreign_user_and_unknown_message_are_rejected(
    provider: PostgresConnectionProvider, owned: _Fixture
) -> None:
    store = PostgresMessageFeedbackStore(provider)

    # A different (valid) user id → not the owner → None.
    foreign = await store.record(
        message_id=owned.message_id,
        rating="down",
        reason=None,
        user_id=str(uuid.uuid4()),
        session_id="foreign-session",
    )
    assert foreign is None

    # An unknown message → None.
    missing = await store.record(
        message_id=uuid4().hex,
        rating="up",
        reason=None,
        user_id=owned.user_id,
        session_id=owned.session_id,
    )
    assert missing is None

    # Nothing was written for the message on the rejected paths.
    assert await store.get_for_message(owned.message_id) is None


async def test_logged_in_user_owns_message_from_a_different_session(
    provider: PostgresConnectionProvider, owned: _Fixture
) -> None:
    # The message was created on ``owned.session_id``; the user now rates it from a *new*
    # session (same user_id) — ownership is by user_id, so this succeeds.
    store = PostgresMessageFeedbackStore(provider)
    result = await store.record(
        message_id=owned.message_id,
        rating="up",
        reason=None,
        user_id=owned.user_id,
        session_id=str(uuid.uuid4()),
    )
    assert result is not None and result.rating == "up"


@pytest_asyncio.fixture
async def guest_owned(provider: PostgresConnectionProvider) -> AsyncIterator[str]:
    """Seed a guest session (user_id NULL) → conversation → message; clean up at the end."""
    session_id = str(uuid.uuid4())
    message_id = uuid4().hex
    async with provider.session() as db:
        db.add(Session(id=session_id))
        conversation = Conversation(session_id=session_id, user_id=None)
        db.add(conversation)
        await db.flush()
        db.add(
            Message(
                conversation_id=conversation.id,
                message_id=message_id,
                role="assistant",
                content="Guest answer.",
            )
        )
        await db.commit()
    try:
        yield f"{session_id}:{message_id}"
    finally:
        async with provider.session() as db:
            existing = await db.get(Session, session_id)
            if existing is not None:
                await db.delete(existing)
                await db.commit()


async def test_guest_owns_message_by_session(
    provider: PostgresConnectionProvider, guest_owned: str
) -> None:
    session_id, message_id = guest_owned.split(":")
    store = PostgresMessageFeedbackStore(provider)

    # Correct guest session → owned.
    ok = await store.record(
        message_id=message_id, rating="up", reason=None, user_id=None, session_id=session_id
    )
    assert ok is not None and ok.rating == "up"

    # A different guest session → not owned.
    denied = await store.record(
        message_id=message_id,
        rating="up",
        reason=None,
        user_id=None,
        session_id=str(uuid.uuid4()),
    )
    assert denied is None
