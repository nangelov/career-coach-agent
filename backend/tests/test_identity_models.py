"""Integration checks for the P2-03 identity/docs schema against **real Postgres**.

These are *not* pure-plumbing tests: they insert one row per new table with valid FKs
and read it back, proving the schema created by migration ``0002`` is actually usable
(JSONB round-trips, FKs resolve, the check constraints and cascade rules behave). They
require the docker-compose Postgres because the schema uses ``JSONB`` and ``UUID`` types
that SQLite cannot represent — the plumbing-only style (SQLite) from P2-01 does not apply
here.

The suite is **skipped automatically** when no Postgres is reachable at ``DATABASE_URL``
(so free-tier CI without a DB service stays green), and it runs entirely inside a single
transaction that is rolled back at the end, leaving the database untouched.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.repositories.models import (
    Conversation,
    Feedback,
    Message,
    MessageFeedback,
    Preference,
    Profile,
    Session,
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

    Skips the whole test if Postgres is unreachable or the ``0002`` schema is not applied
    (the tables must exist — this suite verifies the *applied* migration, it does not
    create the schema itself).
    """
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — integration test skipped")

    engine = create_async_engine(settings.DATABASE_URL)
    conn = await engine.connect()
    trans = await conn.begin()
    db = AsyncSession(bind=conn, expire_on_commit=False)
    try:
        # Fail fast with a clear message if the migration hasn't been applied.
        try:
            await db.execute(select(User).limit(1))
        except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
            pytest.skip("identity schema (migration 0002) not applied — run `alembic upgrade head`")
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
        settings={"theme": "dark"},
    )


async def test_insert_and_read_back_full_graph(session: AsyncSession) -> None:
    """One row per table with valid FKs, read back — proves the schema is usable."""
    user = _make_user()
    session.add(user)
    await session.flush()

    profile = Profile(user_id=user.id, data={"skills": ["python", "sql"]})
    preference = Preference(user_id=user.id, data={"tone": "concise"})
    chat_session = Session(id=str(uuid.uuid4()), user_id=user.id)
    session.add_all([profile, preference, chat_session])
    await session.flush()

    conversation = Conversation(session_id=chat_session.id, user_id=user.id, title="First chat")
    session.add(conversation)
    await session.flush()

    minted_id = uuid4().hex  # mirrors ChatService's message_id shape
    message = Message(
        conversation_id=conversation.id,
        message_id=minted_id,
        role="assistant",
        content="Hello!",
        trace={"tool_calls": []},
    )
    session.add(message)
    await session.flush()

    msg_feedback = MessageFeedback(
        message_id=minted_id, user_id=user.id, session_id=chat_session.id, rating="up"
    )
    product_feedback = Feedback(
        user_id=user.id,
        session_id=chat_session.id,
        contact="user@example.com",
        content="Great tool!",
    )
    session.add_all([msg_feedback, product_feedback])
    await session.flush()

    # Capture PKs before expiring — reading an *expired* ORM attribute to build a query
    # would trigger a sync lazy-load outside the async greenlet.
    user_id = user.id
    session.expire_all()

    # Read back and assert JSONB / FK round-trips.
    fetched_user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    assert fetched_user.settings == {"theme": "dark"}
    assert fetched_user.created_at is not None

    fetched_profile = (
        await session.execute(select(Profile).where(Profile.user_id == user_id))
    ).scalar_one()
    assert fetched_profile.data == {"skills": ["python", "sql"]}

    fetched_msg = (
        await session.execute(select(Message).where(Message.message_id == minted_id))
    ).scalar_one()
    assert fetched_msg.role == "assistant"
    assert fetched_msg.trace == {"tool_calls": []}
    assert len(fetched_msg.message_id) == 32  # uuid4().hex shape

    fetched_mf = (
        await session.execute(
            select(MessageFeedback).where(MessageFeedback.message_id == minted_id)
        )
    ).scalar_one()
    assert fetched_mf.rating == "up"


async def test_users_provider_sub_unique(session: AsyncSession) -> None:
    """The (provider, sub) uniqueness constraint (§7.1 — one identity per provider)."""
    user = _make_user()
    session.add(user)
    await session.flush()

    dup = User(provider=user.provider, sub=user.sub, email="other@example.com")
    # begin_nested() → SAVEPOINT: the expected IntegrityError rolls back only the
    # savepoint, leaving the outer transaction (and the fixture teardown) clean.
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(dup)
            await session.flush()


async def test_message_id_is_unique(session: AsyncSession) -> None:
    """``messages.message_id`` is unique — the natural key feedback references (§5.5)."""
    user = _make_user()
    session.add(user)
    await session.flush()
    chat_session = Session(id=str(uuid.uuid4()), user_id=user.id)
    session.add(chat_session)
    await session.flush()
    conversation = Conversation(session_id=chat_session.id, user_id=user.id)
    session.add(conversation)
    await session.flush()

    shared_id = uuid4().hex
    session.add(
        Message(conversation_id=conversation.id, message_id=shared_id, role="user", content="a")
    )
    await session.flush()
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(
                Message(
                    conversation_id=conversation.id,
                    message_id=shared_id,
                    role="user",
                    content="b",
                )
            )
            await session.flush()


async def test_message_role_check_constraint(session: AsyncSession) -> None:
    """An out-of-vocabulary role is rejected by the CHECK constraint."""
    user = _make_user()
    session.add(user)
    await session.flush()
    chat_session = Session(id=str(uuid.uuid4()), user_id=user.id)
    session.add(chat_session)
    await session.flush()
    conversation = Conversation(session_id=chat_session.id, user_id=user.id)
    session.add(conversation)
    await session.flush()

    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(
                Message(
                    conversation_id=conversation.id,
                    message_id=uuid4().hex,
                    role="robot",  # not in ('system','user','assistant','tool')
                    content="x",
                )
            )
            await session.flush()


async def test_deleting_user_cascades_to_owned_rows(session: AsyncSession) -> None:
    """Deleting a user cascades to profile/session/conversation/message (GDPR, §4)."""
    user = _make_user()
    session.add(user)
    await session.flush()
    chat_session = Session(id=str(uuid.uuid4()), user_id=user.id)
    session.add_all([Profile(user_id=user.id), chat_session])
    await session.flush()
    conversation = Conversation(session_id=chat_session.id, user_id=user.id)
    session.add(conversation)
    await session.flush()
    minted_id = uuid4().hex
    session.add(
        Message(conversation_id=conversation.id, message_id=minted_id, role="user", content="hi")
    )
    await session.flush()

    # Delete at the SQL level so DB-side ON DELETE CASCADE is what we exercise.
    await session.delete(user)
    await session.flush()
    session.expire_all()

    assert (
        await session.execute(select(Profile).where(Profile.user_id == user.id))
    ).first() is None
    assert (
        await session.execute(select(Session).where(Session.id == chat_session.id))
    ).first() is None
    assert (
        await session.execute(select(Message).where(Message.message_id == minted_id))
    ).first() is None


async def test_deleting_user_nulls_product_feedback(session: AsyncSession) -> None:
    """Product ``feedback`` outlives the account — its ``user_id`` is SET NULL (§4)."""
    user = _make_user()
    session.add(user)
    await session.flush()
    feedback = Feedback(user_id=user.id, content="keep me after account delete")
    session.add(feedback)
    await session.flush()
    feedback_id = feedback.id

    await session.delete(user)
    await session.flush()
    session.expire_all()

    surviving = (
        await session.execute(select(Feedback).where(Feedback.id == feedback_id))
    ).scalar_one()
    assert surviving.user_id is None
    assert surviving.content == "keep me after account delete"
