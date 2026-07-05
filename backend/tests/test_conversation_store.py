"""Integration checks for :class:`PostgresConversationStore` against **real Postgres** (P2-07).

Proves the durable-persistence adapter actually writes to and reads from the P2-03 identity
schema (``sessions`` → ``conversations`` → ``messages``): a logged-in turn lands rows with the
right ``message_id``/``role``/``content``, a session's turns share one conversation, and
``load_history`` replays them in order (the restart-rehydration path).

Requires the docker-compose Postgres (JSONB/UUID types SQLite cannot represent). The suite
**skips automatically** when no Postgres is reachable at ``DATABASE_URL`` so free-tier CI
without a DB stays green. Unlike the ORM-model suite, :meth:`persist_turn` commits through its
own session (it owns its transaction), so this test cannot wrap everything in a rolled-back
outer transaction — instead it creates a throwaway user and **deletes it at the end**, which
cascades away every session/conversation/message it created (GDPR cascade, §4), leaving the DB
as found.
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
from app.llm.types import ChatMessage
from app.repositories.conversation_store import PostgresConversationStore
from app.repositories.models.identity import Conversation, Message, User
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
    """A real Postgres provider; skips if unreachable or the 0002 schema is not applied."""
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — integration test skipped")
    prov = PostgresConnectionProvider.from_settings(settings)
    # Fail fast → skip if the identity schema (migration 0002) has not been applied.
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


@pytest_asyncio.fixture
async def user_id(provider: PostgresConnectionProvider) -> AsyncIterator[str]:
    """Create a throwaway user; delete it at the end (cascades away everything created)."""
    unique = uuid4().hex[:12]
    async with provider.session() as db:
        user = User(provider="google", sub=f"sub-{unique}", email=f"u-{unique}@example.com")
        db.add(user)
        await db.commit()
        uid = str(user.id)
    try:
        yield uid
    finally:
        async with provider.session() as db:
            existing = await db.get(User, uuid.UUID(uid))
            if existing is not None:
                await db.delete(existing)
                await db.commit()


async def test_persist_turn_writes_conversation_and_messages(
    provider: PostgresConnectionProvider, user_id: str
) -> None:
    store = PostgresConversationStore(provider)
    session_id = str(uuid.uuid4())
    assistant_id = uuid4().hex

    conv_id = await store.persist_turn(
        user_id=user_id,
        session_id=session_id,
        conversation_id=None,
        user_message=ChatMessage(role="user", content="what should I learn?"),
        assistant_message=ChatMessage(
            role="assistant", content="Start with Python.", message_id=assistant_id
        ),
    )

    async with provider.session() as db:
        conv = await db.get(Conversation, uuid.UUID(conv_id))
        assert conv is not None
        assert conv.session_id == session_id
        assert str(conv.user_id) == user_id

        rows = (
            (await db.execute(select(Message).where(Message.conversation_id == uuid.UUID(conv_id))))
            .scalars()
            .all()
        )
        by_role = {m.role: m for m in rows}
        assert by_role["user"].content == "what should I learn?"
        assert by_role["assistant"].content == "Start with Python."
        # The turn's stable message_id is preserved on the assistant row (§5.5).
        assert by_role["assistant"].message_id == assistant_id


async def test_second_turn_reuses_conversation_and_load_history_orders(
    provider: PostgresConnectionProvider, user_id: str
) -> None:
    store = PostgresConversationStore(provider)
    session_id = str(uuid.uuid4())

    conv1 = await store.persist_turn(
        user_id=user_id,
        session_id=session_id,
        conversation_id=None,
        user_message=ChatMessage(role="user", content="hi"),
        assistant_message=ChatMessage(role="assistant", content="hello", message_id=uuid4().hex),
    )
    conv2 = await store.persist_turn(
        user_id=user_id,
        session_id=session_id,
        conversation_id=None,
        user_message=ChatMessage(role="user", content="how are you"),
        assistant_message=ChatMessage(role="assistant", content="great", message_id=uuid4().hex),
    )
    # Both turns of a session land in the same conversation.
    assert conv1 == conv2

    history = await store.load_history(user_id=user_id, session_id=session_id)
    assert [(m.role, m.content) for m in history] == [
        ("user", "hi"),
        ("assistant", "hello"),
        ("user", "how are you"),
        ("assistant", "great"),
    ]


async def test_persist_turn_without_assistant_stores_only_user(
    provider: PostgresConnectionProvider, user_id: str
) -> None:
    # A cancel-before-any-content turn: the user's question is still preserved.
    store = PostgresConversationStore(provider)
    session_id = str(uuid.uuid4())

    await store.persist_turn(
        user_id=user_id,
        session_id=session_id,
        conversation_id=None,
        user_message=ChatMessage(role="user", content="cut me off"),
        assistant_message=None,
    )

    history = await store.load_history(user_id=user_id, session_id=session_id)
    assert [(m.role, m.content) for m in history] == [("user", "cut me off")]


async def test_load_history_empty_for_unknown_session(
    provider: PostgresConnectionProvider, user_id: str
) -> None:
    store = PostgresConversationStore(provider)
    history = await store.load_history(user_id=user_id, session_id=str(uuid.uuid4()))
    assert history == []
