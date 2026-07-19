"""Live-Postgres integration test for the teachable-memory learn step (P9-03, §5.4 / §5.5).

Proves the P9-03 write path works against the **real** ``user_memories`` schema (the
``vector(4096)`` + FKs SQLite cannot represent): the :class:`~app.memory.store.UserMemoryStore`
write methods (``add_memory`` / ``update_memory`` / ``delete_memory`` /
``list_memories_for_message``) persist correctly, and the full injectable core
:func:`~app.memory.learn.run_learn_from_turn` — driven by a fake extractor + the **real**
:class:`~app.repositories.message_feedback_store.PostgresMessageFeedbackStore` — inserts a new
memory, reinforces a near-duplicate rather than duplicating it, and demotes/removes a memory a
real thumb-down disowned.

Only the embedder and the extractor are fakes (no 8B model, no HF); the DB and the feedback store
are real. Skips cleanly when no Postgres / the schema is unreachable, matching the P2/P5/P9-01
live-DB convention. A throwaway user is created and **deleted at the end**, cascading away its
memories/messages/feedback (GDPR cascade, §4), leaving the DB as found.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.memory.learn import LearnConfig, MemoryCandidate, run_learn_from_turn
from app.memory.store import UserMemoryStore
from app.repositories.message_feedback_store import PostgresMessageFeedbackStore
from app.repositories.models.identity import Conversation, Message, Session, User
from app.repositories.models.knowledge import EMBEDDING_DIM, UserMemory
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


class _FixedEmbedder:
    """Embedder returning a valid 4096-dim vector (matches the real column width).

    A **non-zero** constant on purpose: pgvector's cosine distance is undefined (NaN) for a
    zero vector, so two zero embeddings would never register as similar. A shared non-zero
    constant makes every embedding identical → cosine similarity 1.0, which is what the dedup
    path needs to exercise the near-duplicate branch.
    """

    def __init__(self, value: float = 0.1) -> None:
        self._value = value

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[self._value] * EMBEDDING_DIM for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [self._value] * EMBEDDING_DIM


class _StaticExtractor:
    """Returns a fixed candidate list regardless of the exchange."""

    def __init__(self, candidates: list[MemoryCandidate]) -> None:
        self._candidates = candidates

    async def propose(self, *, user_text: str, assistant_text: str) -> list[MemoryCandidate]:
        return list(self._candidates)


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
        pytest.skip("knowledge schema not applied — run `alembic upgrade head`")
    try:
        yield prov
    finally:
        await prov.aclose()


class _Seed:
    def __init__(self, user_id: str, session_id: str, message_id: str) -> None:
        self.user_id = user_id
        self.session_id = session_id
        self.message_id = message_id


@pytest_asyncio.fixture
async def seed(provider: PostgresConnectionProvider) -> AsyncIterator[_Seed]:
    """Seed user → session → conversation → assistant message; delete the user at the end."""
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
                content="Some advice.",
            )
        )
        uid = str(user.id)
        await db.commit()
    try:
        yield _Seed(uid, session_id, message_id)
    finally:
        async with provider.session() as db:
            existing = await db.get(User, uuid.UUID(uid))
            if existing is not None:
                await db.delete(existing)
                await db.commit()


async def _count_memories(provider: PostgresConnectionProvider, user_id: str) -> int:
    async with provider.session() as db:
        result = await db.execute(
            select(func.count())
            .select_from(UserMemory)
            .where(UserMemory.user_id == uuid.UUID(user_id))
        )
        return int(result.scalar_one())


async def test_store_write_methods_roundtrip(
    provider: PostgresConnectionProvider, seed: _Seed
) -> None:
    store = UserMemoryStore(embedder=_FixedEmbedder(), db=provider)  # type: ignore[arg-type]

    memory_id = await store.add_memory(
        uuid.UUID(seed.user_id),
        "prefers bullet points",
        memory_type="style",
        confidence=0.8,
        source_message_id=seed.message_id,
    )
    records = await store.list_memories_for_message(uuid.UUID(seed.user_id), seed.message_id)
    assert [r.memory_id for r in records] == [memory_id]
    assert records[0].confidence == 0.8

    assert await store.update_memory(memory_id, confidence=0.5) is True
    records = await store.list_memories_for_message(uuid.UUID(seed.user_id), seed.message_id)
    assert records[0].confidence == 0.5

    assert await store.delete_memory(memory_id) is True
    assert await _count_memories(provider, seed.user_id) == 0
    # Deleting a non-existent row is a benign False.
    assert await store.delete_memory(uuid4()) is False


async def test_learn_inserts_then_dedupes_against_real_search(
    provider: PostgresConnectionProvider, seed: _Seed
) -> None:
    store = UserMemoryStore(embedder=_FixedEmbedder(), db=provider)  # type: ignore[arg-type]
    feedback = PostgresMessageFeedbackStore.from_provider(provider)
    extractor = _StaticExtractor(
        [
            MemoryCandidate(
                text="targeting product management", memory_type="preference", confidence=0.8
            )
        ]
    )

    # First turn → inserts the memory.
    first = await run_learn_from_turn(
        user_id=seed.user_id,
        message_id=seed.message_id,
        user_text="I want to move into product",
        assistant_text="Great goal.",
        store=store,
        extractor=extractor,
        feedback=feedback,
    )
    assert len(first.inserted) == 1
    assert await _count_memories(provider, seed.user_id) == 1

    # Second turn with the same candidate → the fixed embedder makes cosine similarity 1.0, so
    # the near-duplicate reinforces the existing row instead of inserting a twin.
    second = await run_learn_from_turn(
        user_id=seed.user_id,
        message_id=seed.message_id,
        user_text="still aiming for product",
        assistant_text="Keep going.",
        store=store,
        extractor=extractor,
        feedback=feedback,
    )
    assert second.updated and not second.inserted
    assert await _count_memories(provider, seed.user_id) == 1  # still one, not duplicated


async def test_learn_demotes_on_real_thumb_down(
    provider: PostgresConnectionProvider, seed: _Seed
) -> None:
    store = UserMemoryStore(embedder=_FixedEmbedder(), db=provider)  # type: ignore[arg-type]
    feedback = PostgresMessageFeedbackStore.from_provider(provider)

    # A memory learned from this turn, at a confidence one demotion pushes to the floor.
    memory_id = await store.add_memory(
        uuid.UUID(seed.user_id),
        "generic advice memory",
        memory_type="fact",
        confidence=0.3,
        source_message_id=seed.message_id,
    )

    # The user thumbs the turn down.
    recorded = await feedback.record(
        message_id=seed.message_id,
        rating="down",
        reason="too generic",
        user_id=seed.user_id,
        session_id=seed.session_id,
    )
    assert recorded is not None

    result = await run_learn_from_turn(
        user_id=seed.user_id,
        message_id=seed.message_id,
        user_text="useless",
        assistant_text="generic advice",
        store=store,
        extractor=_StaticExtractor([]),
        feedback=feedback,
        config=LearnConfig(demote_decrement=0.3, remove_floor=0.1),
    )

    # 0.3 - 0.3 = 0.0 <= floor → removed. An explicit "avoid: too generic" preference is learned.
    assert result.removed == [memory_id]
    async with provider.session() as db:
        remaining = (
            (
                await db.execute(
                    select(UserMemory.text).where(UserMemory.user_id == uuid.UUID(seed.user_id))
                )
            )
            .scalars()
            .all()
        )
    assert any("too generic" in t for t in remaining)
    assert all("generic advice memory" != t for t in remaining)


async def test_standing_downvote_demotes_once_against_real_updated_at(
    provider: PostgresConnectionProvider, seed: _Seed
) -> None:
    # Regression (code-review C1): the demotion idempotency relies on the real ``user_memories``
    # ``onupdate=now()`` moving a demoted row's ``updated_at`` past the vote. Two consecutive learn
    # passes over one standing thumb-down must demote the memory exactly once, never to deletion.
    store = UserMemoryStore(embedder=_FixedEmbedder(), db=provider)  # type: ignore[arg-type]
    feedback = PostgresMessageFeedbackStore.from_provider(provider)

    memory_id = await store.add_memory(
        uuid.UUID(seed.user_id),
        "memory to demote once",
        memory_type="fact",
        confidence=0.9,  # two demotions would reach the floor; one keeps it at 0.6
        source_message_id=seed.message_id,
    )
    recorded = await feedback.record(
        message_id=seed.message_id,
        rating="down",
        reason=None,
        user_id=seed.user_id,
        session_id=seed.session_id,
    )
    assert recorded is not None
    cfg = LearnConfig(demote_decrement=0.3, remove_floor=0.1)

    first = await run_learn_from_turn(
        user_id=seed.user_id,
        message_id="later-1",
        user_text="unrelated later turn",
        assistant_text="ok",
        store=store,
        extractor=_StaticExtractor([]),
        feedback=feedback,
        config=cfg,
    )
    assert first.demoted == [memory_id]

    second = await run_learn_from_turn(
        user_id=seed.user_id,
        message_id="later-2",
        user_text="another later turn",
        assistant_text="ok",
        store=store,
        extractor=_StaticExtractor([]),
        feedback=feedback,
        config=cfg,
    )
    assert second.demoted == [] and second.removed == []  # not re-demoted, not deleted

    records = await store.list_memories_for_message(uuid.UUID(seed.user_id), seed.message_id)
    assert [r.memory_id for r in records] == [memory_id]
    assert records[0].confidence == pytest.approx(0.6)  # single demotion, not compounded
