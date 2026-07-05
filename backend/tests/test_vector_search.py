"""Integration tests for the P2-06 pgvector write + hybrid-search helpers (real Postgres).

These prove the ``vector_search`` repository helpers actually work against the P2-04 schema:
the write helpers insert into ``kb_chunks`` / ``user_memories``, and — the core of the task —
:func:`~app.repositories.vector_search.hybrid_search_chunks` blends cosine similarity and
lexical ``ts_rank`` with **caller-configurable weights** such that *changing the weights
changes the ranking*. That weighting proof needs real ``vector(4096)`` + generated
``tsvector`` columns, so (like ``test_knowledge_models.py``) the suite runs against the
docker-compose Postgres and **skips cleanly** when no DB / the ``0003`` schema is reachable.
It runs inside one transaction that is rolled back, leaving the database untouched.

The embeddings are controlled fakes (orthogonal one-hot vectors) built here — the real 8B
model is never involved (see ``test_embeddings.py`` for the client seam).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.repositories.models import KbChunk, KbDocument, User, UserMemory
from app.repositories.models.knowledge import EMBEDDING_DIM
from app.repositories.vector_search import (
    add_kb_chunk,
    add_user_memory,
    hybrid_search_chunks,
    search_user_memories,
)


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
async def session() -> AsyncIterator[AsyncSession]:
    """A rolled-back session; skips if Postgres / the 0003 schema is not reachable."""
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
    """A 4096-dim unit vector with a single 1.0 at ``index`` (orthogonal, predictable)."""
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


async def test_add_kb_chunk_persists_row(session: AsyncSession) -> None:
    doc = KbDocument(title="doc", source_type="curated")
    session.add(doc)
    await session.flush()

    chunk = await add_kb_chunk(
        session,
        kb_document_id=doc.id,
        chunk_index=0,
        content="Interview preparation for software engineers.",
        embedding=_one_hot(3),
        meta={"section": "intro"},
    )

    assert chunk.id is not None
    fetched = (await session.execute(select(KbChunk).where(KbChunk.id == chunk.id))).scalar_one()
    assert fetched.content.startswith("Interview preparation")
    assert len(fetched.embedding) == EMBEDDING_DIM
    assert fetched.meta == {"section": "intro"}
    # The generated tsvector was populated by Postgres from the inserted content.
    assert fetched.content_tsv


async def test_add_user_memory_persists_row(session: AsyncSession) -> None:
    user = _make_user()
    session.add(user)
    await session.flush()

    memory = await add_user_memory(
        session,
        user_id=user.id,
        text="prefers concise answers",
        embedding=_one_hot(1),
        memory_type="preference",
        confidence=0.8,
    )

    assert memory.id is not None
    fetched = (
        await session.execute(select(UserMemory).where(UserMemory.id == memory.id))
    ).scalar_one()
    assert fetched.text == "prefers concise answers"
    assert fetched.memory_type == "preference"
    assert fetched.confidence == pytest.approx(0.8)


async def test_hybrid_search_weights_change_ranking(session: AsyncSession) -> None:
    """The heart of the task: the SAME query ranks differently as the weights shift.

    Two chunks are constructed so the two signals disagree:

    * ``lexical`` — content lexically matches the query word "kubernetes" but its embedding
      is orthogonal to the query vector (vector-distant).
    * ``semantic`` — content is lexically unrelated to "kubernetes" but its embedding EQUALS
      the query vector (cosine distance 0).

    With text weight dominating, the lexical match must win; with vector weight dominating,
    the semantic match must win. That flip is the proof the weights actually blend.
    """
    doc = KbDocument(title="doc", source_type="curated")
    session.add(doc)
    await session.flush()

    lexical = await add_kb_chunk(
        session,
        kb_document_id=doc.id,
        chunk_index=0,
        content="Kubernetes orchestrates containerized workloads at scale.",
        embedding=_one_hot(10),  # orthogonal to the query vector below
    )
    semantic = await add_kb_chunk(
        session,
        kb_document_id=doc.id,
        chunk_index=1,
        content="Negotiating a fair salary during job interviews.",
        embedding=_one_hot(20),  # equals the query vector below
    )
    doc_id = doc.id
    lexical_id = lexical.id
    semantic_id = semantic.id

    query_text = "kubernetes"
    query_embedding = _one_hot(20)  # identical to ``semantic``'s embedding

    # Text-dominant: the lexical "kubernetes" match ranks first.
    text_first = await hybrid_search_chunks(
        session,
        query_embedding=query_embedding,
        query_text=query_text,
        k=2,
        vector_weight=0.0,
        text_weight=1.0,
        kb_document_ids=[doc_id],
    )
    assert [r.chunk_id for r in text_first][0] == lexical_id

    # Vector-dominant: the semantically identical chunk ranks first — ranking flipped.
    vector_first = await hybrid_search_chunks(
        session,
        query_embedding=query_embedding,
        query_text=query_text,
        k=2,
        vector_weight=1.0,
        text_weight=0.0,
        kb_document_ids=[doc_id],
    )
    assert [r.chunk_id for r in vector_first][0] == semantic_id

    # Sanity: the raw component signals are exposed and sane.
    by_id = {r.chunk_id: r for r in vector_first}
    assert by_id[semantic_id].vector_similarity == pytest.approx(1.0, abs=1e-6)
    assert by_id[lexical_id].vector_similarity == pytest.approx(0.0, abs=1e-6)


async def test_hybrid_search_respects_limit_and_document_filter(session: AsyncSession) -> None:
    doc_a = KbDocument(title="A", source_type="curated")
    doc_b = KbDocument(title="B", source_type="curated")
    session.add_all([doc_a, doc_b])
    await session.flush()

    await add_kb_chunk(
        session,
        kb_document_id=doc_a.id,
        chunk_index=0,
        content="Python asyncio patterns for backend services.",
        embedding=_one_hot(0),
    )
    await add_kb_chunk(
        session,
        kb_document_id=doc_b.id,
        chunk_index=0,
        content="Python asyncio patterns for backend services.",
        embedding=_one_hot(0),
    )
    doc_a_id = doc_a.id

    results = await hybrid_search_chunks(
        session,
        query_embedding=_one_hot(0),
        query_text="python asyncio",
        k=5,
        kb_document_ids=[doc_a_id],
    )
    assert len(results) == 1
    assert results[0].kb_document_id == doc_a_id


async def test_search_user_memories_vector_only(session: AsyncSession) -> None:
    """Vector-only memory search returns the nearest memory for the user (§5.4)."""
    user = _make_user()
    session.add(user)
    await session.flush()

    await add_user_memory(
        session,
        user_id=user.id,
        text="prefers bullet-point answers",
        embedding=_one_hot(0),
        memory_type="preference",
    )
    await add_user_memory(
        session,
        user_id=user.id,
        text="based in Berlin",
        embedding=_one_hot(1),
        memory_type="fact",
    )
    user_id = user.id

    results = await search_user_memories(session, user_id=user_id, query_embedding=_one_hot(0), k=1)
    assert len(results) == 1
    assert results[0].text == "prefers bullet-point answers"
    assert results[0].similarity == pytest.approx(1.0, abs=1e-6)


async def test_search_user_memories_is_scoped_to_user(session: AsyncSession) -> None:
    """A user's memory search never returns another user's memories."""
    user_a = _make_user()
    user_b = _make_user()
    session.add_all([user_a, user_b])
    await session.flush()

    await add_user_memory(
        session,
        user_id=user_b.id,
        text="user B secret",
        embedding=_one_hot(0),
        memory_type="fact",
    )
    user_a_id = user_a.id

    results = await search_user_memories(
        session, user_id=user_a_id, query_embedding=_one_hot(0), k=5
    )
    assert results == []
