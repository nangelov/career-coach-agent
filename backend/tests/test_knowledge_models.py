"""Integration checks for the P2-04 knowledge/vector schema against **real Postgres**.

These prove the pgvector table group created by migration ``0003`` is actually usable:
JSONB round-trips, the ``vector(4096)`` columns store and search, the generated
``tsvector`` full-text column populates, and the check/cascade rules behave. Crucially
they exercise the **P2 exit criterion** — an ``ORDER BY embedding <=> :q`` cosine
similarity query returns the expected nearest neighbour — on both ``kb_chunks`` and
``user_memories``.

They require the docker-compose Postgres (``JSONB``/``UUID``/``vector`` cannot be
represented in SQLite). The suite is **skipped automatically** when no Postgres is
reachable at ``DATABASE_URL`` (so free-tier CI without a DB service stays green), and it
runs entirely inside a single transaction that is rolled back at the end, leaving the
database untouched.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.repositories.models import (
    Conversation,
    KbChunk,
    KbDocument,
    Message,
    Session,
    User,
    UserMemory,
)
from app.repositories.models.knowledge import EMBEDDING_DIM


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

    Skips the whole test if Postgres is unreachable or the ``0003`` schema is not applied
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
        try:
            await db.execute(select(KbDocument).limit(1))
        except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
            pytest.skip(
                "knowledge schema (migration 0003) not applied — run `alembic upgrade head`"
            )
        yield db
    finally:
        await db.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()


def _one_hot(index: int) -> list[float]:
    """A 4096-dim unit vector with a single 1.0 at ``index`` — gives clean, orthogonal
    embeddings whose cosine distances are trivially predictable (0 to itself, 1 to any
    other one-hot)."""
    vec = [0.0] * EMBEDDING_DIM
    vec[index] = 1.0
    return vec


def _make_user() -> User:
    unique = uuid4().hex[:12]
    return User(
        provider="google",
        sub=f"sub-{unique}",
        email=f"user-{unique}@example.com",
        display_name="Test User",
    )


async def test_kb_document_and_chunks_round_trip(session: AsyncSession) -> None:
    """Insert a document + chunks, read back — JSONB, vector and tsvector all usable."""
    doc = KbDocument(
        title="Curated: switching into product management",
        source="https://example.com/pm-guide",
        source_type="curated",
        content="Full article text.",
        meta={"lang": "en"},
    )
    session.add(doc)
    await session.flush()

    chunk = KbChunk(
        kb_document_id=doc.id,
        chunk_index=0,
        content="Product managers coordinate engineering, design and business.",
        embedding=_one_hot(0),
        meta={"section": "intro"},
    )
    session.add(chunk)
    await session.flush()
    chunk_id = chunk.id
    session.expire_all()

    fetched = (await session.execute(select(KbChunk).where(KbChunk.id == chunk_id))).scalar_one()
    assert fetched.meta == {"section": "intro"}
    assert len(fetched.embedding) == EMBEDDING_DIM
    # The generated tsvector column is populated by Postgres from ``content``.
    assert fetched.content_tsv is not None and fetched.content_tsv != ""


async def test_kb_chunks_cosine_similarity_nearest_neighbor(session: AsyncSession) -> None:
    """P2 exit criterion: ``ORDER BY embedding <=> :q`` returns the expected neighbour."""
    doc = KbDocument(title="doc", source_type="curated")
    session.add(doc)
    await session.flush()

    # Three orthogonal chunks. The probe equals ``near``'s embedding (cosine distance 0);
    # the others are orthogonal (cosine distance 1), so ``near`` must sort first.
    near = KbChunk(kb_document_id=doc.id, chunk_index=0, content="near", embedding=_one_hot(0))
    far_a = KbChunk(kb_document_id=doc.id, chunk_index=1, content="far a", embedding=_one_hot(1))
    far_b = KbChunk(kb_document_id=doc.id, chunk_index=2, content="far b", embedding=_one_hot(2))
    session.add_all([near, far_a, far_b])
    await session.flush()
    # Capture PKs before expiring — reading an expired attribute to build a query would
    # trigger a sync lazy-load outside the async greenlet.
    near_id = near.id
    doc_id = doc.id
    session.expire_all()

    probe = _one_hot(0)
    rows = (
        (
            await session.execute(
                select(KbChunk)
                .where(KbChunk.kb_document_id == doc_id)
                .order_by(KbChunk.embedding.cosine_distance(probe))
                .limit(1)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].id == near_id  # nearest neighbour is the matching chunk


async def test_user_memory_cosine_similarity_and_cascade(session: AsyncSession) -> None:
    """user_memories: similarity query works and rows cascade-delete with the user (§4)."""
    user = _make_user()
    session.add(user)
    await session.flush()

    near = UserMemory(
        user_id=user.id,
        text="prefers concise, bullet-point answers",
        embedding=_one_hot(0),
        memory_type="preference",
        confidence=0.9,
    )
    far = UserMemory(
        user_id=user.id,
        text="based in Berlin",
        embedding=_one_hot(1),
        memory_type="fact",
    )
    session.add_all([near, far])
    await session.flush()
    near_id = near.id
    user_id = user.id
    session.expire_all()

    probe = _one_hot(0)
    top = (
        await session.execute(
            select(UserMemory)
            .where(UserMemory.user_id == user_id)
            .order_by(UserMemory.embedding.cosine_distance(probe))
            .limit(1)
        )
    ).scalar_one()
    assert top.id == near_id

    # GDPR cascade: deleting the user removes their memories.
    user_row = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    await session.delete(user_row)
    await session.flush()
    session.expire_all()
    remaining = (
        await session.execute(select(UserMemory).where(UserMemory.user_id == user_id))
    ).first()
    assert remaining is None


async def test_kb_chunks_full_text_search(session: AsyncSession) -> None:
    """The generated tsvector + GIN index supports lexical search (hybrid-search half)."""
    doc = KbDocument(title="doc", source_type="curated")
    session.add(doc)
    await session.flush()
    session.add_all(
        [
            KbChunk(
                kb_document_id=doc.id,
                chunk_index=0,
                content="Kubernetes orchestrates containerized workloads.",
                embedding=_one_hot(0),
            ),
            KbChunk(
                kb_document_id=doc.id,
                chunk_index=1,
                content="Negotiating a fair salary during interviews.",
                embedding=_one_hot(1),
            ),
        ]
    )
    await session.flush()
    session.expire_all()

    hits = (
        (
            await session.execute(
                select(KbChunk).where(
                    KbChunk.content_tsv.op("@@")(func.to_tsquery("english", "salary"))
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(hits) == 1
    assert "salary" in hits[0].content.lower()


async def test_source_type_check_constraint(session: AsyncSession) -> None:
    """An out-of-vocabulary ``source_type`` is rejected by the CHECK constraint."""
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(KbDocument(title="bad", source_type="nonsense"))
            await session.flush()


async def test_memory_type_check_constraint(session: AsyncSession) -> None:
    """An out-of-vocabulary ``memory_type`` is rejected by the CHECK constraint."""
    user = _make_user()
    session.add(user)
    await session.flush()
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(
                UserMemory(
                    user_id=user.id,
                    text="x",
                    embedding=_one_hot(0),
                    memory_type="mood",  # not in ('preference','fact','style')
                )
            )
            await session.flush()


async def test_deleting_document_cascades_to_chunks(session: AsyncSession) -> None:
    """Deleting a kb_document removes its chunks (FK cascade)."""
    doc = KbDocument(title="doc", source_type="curated")
    session.add(doc)
    await session.flush()
    session.add(KbChunk(kb_document_id=doc.id, chunk_index=0, content="c", embedding=_one_hot(0)))
    await session.flush()
    doc_id = doc.id

    await session.delete(doc)
    await session.flush()
    session.expire_all()
    assert (
        await session.execute(select(KbChunk).where(KbChunk.kb_document_id == doc_id))
    ).first() is None


async def test_user_cv_document_cascades_with_user(session: AsyncSession) -> None:
    """A user's private (user_cv) document is erased on user-delete; shared docs are not."""
    user = _make_user()
    session.add(user)
    await session.flush()
    private = KbDocument(title="Alice CV", source="user-cv", source_type="user_cv", user_id=user.id)
    shared = KbDocument(title="Shared guide", source_type="curated")  # user_id NULL
    session.add_all([private, shared])
    await session.flush()
    private_id, shared_id, user_id = private.id, shared.id, user.id

    user_row = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    await session.delete(user_row)
    await session.flush()
    session.expire_all()

    assert (
        await session.execute(select(KbDocument).where(KbDocument.id == private_id))
    ).first() is None
    # Shared curated content survives — it belongs to no single user.
    assert (
        await session.execute(select(KbDocument).where(KbDocument.id == shared_id))
    ).scalar_one() is not None


async def test_user_memory_source_message_set_null(session: AsyncSession) -> None:
    """Deleting the source message nulls ``source_message_id`` (memory survives, §5.5)."""
    user = _make_user()
    session.add(user)
    await session.flush()
    chat_session = Session(id=str(uuid.uuid4()), user_id=user.id)
    session.add(chat_session)
    await session.flush()
    conversation = Conversation(session_id=chat_session.id, user_id=user.id)
    session.add(conversation)
    await session.flush()
    minted_id = uuid4().hex
    session.add(
        Message(conversation_id=conversation.id, message_id=minted_id, role="user", content="hi")
    )
    await session.flush()

    memory = UserMemory(
        user_id=user.id,
        text="learned from a turn",
        embedding=_one_hot(0),
        memory_type="fact",
        source_message_id=minted_id,
    )
    session.add(memory)
    await session.flush()
    memory_id = memory.id

    # Delete only the message (not the user) → SET NULL, memory survives detached.
    msg = (
        await session.execute(select(Message).where(Message.message_id == minted_id))
    ).scalar_one()
    await session.delete(msg)
    await session.flush()
    session.expire_all()

    surviving = (
        await session.execute(select(UserMemory).where(UserMemory.id == memory_id))
    ).scalar_one()
    assert surviving.source_message_id is None
