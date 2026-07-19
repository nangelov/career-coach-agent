"""pgvector write + hybrid-search helpers over the P2-04 knowledge schema (§4).

This is the **repository-layer** primitive the RAG retrieval agent (P4/P5) and LangMem
(P9) will sit on: it turns an :class:`~app.llm.embeddings.EmbeddingClient` output into rows
in the P2-04 ``kb_chunks`` / ``user_memories`` tables and searches them. All datastore
access lives here (services never touch the driver — §8 layering); the ORM models are the
ones P2-04 already defined (:mod:`app.repositories.models.knowledge`), not re-declared.

Three things live here:

* **Write helpers** (:func:`add_kb_chunk`, :func:`add_user_memory`) — insert a row given
  precomputed text + embedding, wiring the embedding client's output into the schema. They
  ``flush`` (so the PK is populated) but never ``commit`` — the caller owns the transaction
  boundary, matching :func:`app.repositories.postgres.get_db_session`.
* **Hybrid search** (:func:`hybrid_search_chunks`, and the embed-then-search convenience
  :func:`hybrid_search`) over ``kb_chunks`` — blends **cosine similarity** and **lexical
  ``ts_rank``** with **caller-configurable weights** (design ask: *"Hybrid Search with
  weights"*, §4/tasks P2).
* **Vector-only memory search** (:func:`search_user_memories`) — cosine-similarity search
  over ``user_memories``. It is intentionally **not** hybrid: P2-04 gave that table no
  ``tsvector``/GIN column (LangMem recalls memories by semantic similarity to the turn, not
  lexically), so there is no lexical signal to blend.

**Blending strategy — Reciprocal Rank Fusion (RRF), chosen over min-max score blending.**
The two signals live on incomparable scales (pgvector cosine similarity ``1 - (embedding
<=> q)`` is ~[0, 1]; ``ts_rank`` is unbounded-small and corpus-dependent), so a raw weighted
sum ``w_v * cos + w_t * ts_rank`` would let whichever signal happens to have the larger
magnitude dominate regardless of the weights. RRF fuses the two **rankings** instead of the
raw scores: ``score = w_v / (rrf_k + rank_vector) + w_t / (rrf_k + rank_text)``. It is
scale-invariant, so the weights control each signal's influence directly and predictably
(the property the "weights" ask requires and the integration test asserts), and it is the
standard, well-documented fusion for combining a dense and a lexical ranker. ``rrf_k`` (the
smoothing constant, default 60 per the original RRF paper) damps the influence of very low
ranks. The raw ``vector_similarity`` and ``text_rank`` are still returned for transparency.

**Scale note (documented follow-up, not a blocker here).** :func:`hybrid_search_chunks`
ranks over the full candidate set (optionally document-filtered) with **exact** cosine on
the full-precision ``vector(4096)`` column — correct at any corpus size and right for the
current (small) data. At scale the exact scan is the bottleneck: the intended optimization
is to prefilter top-N candidates via the P2-04 ``binary_quantize(embedding)::bit(4096)
bit_hamming_ops`` HNSW index, then RRF-rerank those candidates by exact cosine. That
prefilter is an optimization over the *same* result contract and is deferred (see the P2-04
``engineer.md`` flag) — the weighting correctness this task must prove is independent of it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from typing import cast as type_cast

from sqlalchemy import Float, cast, delete, func, select

from app.repositories.models.knowledge import KbChunk, UserMemory

if TYPE_CHECKING:
    from sqlalchemy import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.llm.embeddings import EmbeddingClient

#: RRF smoothing constant (original RRF paper default). Larger → flatter contribution across
#: ranks; smaller → sharper preference for top-ranked items.
DEFAULT_RRF_K = 60


@dataclass(frozen=True)
class SearchResult:
    """One ranked ``kb_chunks`` hit from :func:`hybrid_search_chunks`.

    :attr:`score` is the fused RRF score results are ordered by; :attr:`vector_similarity`
    (``1 - cosine_distance``) and :attr:`text_rank` (``ts_rank``) are the raw component
    signals, exposed for debugging/telemetry and downstream reranking.
    """

    chunk_id: uuid.UUID
    kb_document_id: uuid.UUID
    content: str
    score: float
    vector_similarity: float
    text_rank: float
    meta: dict[str, Any]


@dataclass(frozen=True)
class MemorySearchResult:
    """One cosine-ranked ``user_memories`` hit from :func:`search_user_memories`."""

    memory_id: uuid.UUID
    text: str
    similarity: float
    memory_type: str
    confidence: float


@dataclass(frozen=True)
class UserMemoryRecord:
    """A plain (non-vector) projection of one ``user_memories`` row.

    Returned by :func:`list_user_memories_by_source_message` so the learn step (P9-03) can
    apply its demotion policy without loading the heavy 4096-dim embedding column.

    :attr:`updated_at` is carried so the demotion pass can be **idempotent**: a memory whose
    ``updated_at`` is at/after a down-vote's timestamp was already learned or demoted in response
    to that vote, so a standing down-vote in the recent window is not re-applied every later pass.
    """

    memory_id: uuid.UUID
    text: str
    memory_type: str
    confidence: float
    source_message_id: str | None
    updated_at: datetime


@dataclass(frozen=True)
class UserMemoryListItem:
    """A panel-facing projection of one ``user_memories`` row (P9-05 memory panel).

    The columns the "what the coach knows about you" surface shows — id, text, type, confidence
    and ``created_at`` — with the heavy 4096-dim embedding deliberately excluded (§7.6: a derived
    artifact never crosses the wire). Distinct from :class:`UserMemoryRecord` (the learn step's
    demotion projection, which carries ``updated_at``/``source_message_id`` instead).
    """

    memory_id: uuid.UUID
    text: str
    memory_type: str
    confidence: float
    created_at: datetime


async def add_kb_chunk(
    session: AsyncSession,
    *,
    kb_document_id: uuid.UUID,
    chunk_index: int,
    content: str,
    embedding: Sequence[float],
    meta: dict[str, Any] | None = None,
) -> KbChunk:
    """Insert a ``kb_chunks`` row from precomputed text + embedding; return it (PK populated).

    Does not commit — the caller owns the transaction (see module docstring). The generated
    ``content_tsv`` is maintained by Postgres from ``content``; do not pass it.
    """
    chunk = KbChunk(
        kb_document_id=kb_document_id,
        chunk_index=chunk_index,
        content=content,
        embedding=list(embedding),
        meta=meta or {},
    )
    session.add(chunk)
    await session.flush()
    return chunk


async def add_user_memory(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    text: str,
    embedding: Sequence[float],
    memory_type: str,
    confidence: float = 1.0,
    source_message_id: str | None = None,
) -> UserMemory:
    """Insert a ``user_memories`` row from precomputed text + embedding; return it.

    Does not commit — the caller owns the transaction. ``memory_type`` must be one of the
    P2-04 check-constraint values (``preference`` / ``fact`` / ``style``).
    """
    memory = UserMemory(
        user_id=user_id,
        text=text,
        embedding=list(embedding),
        memory_type=memory_type,
        confidence=confidence,
        source_message_id=source_message_id,
    )
    session.add(memory)
    await session.flush()
    return memory


async def update_user_memory(
    session: AsyncSession,
    *,
    memory_id: uuid.UUID,
    text: str | None = None,
    embedding: Sequence[float] | None = None,
    confidence: float | None = None,
) -> bool:
    """Update a ``user_memories`` row in place; return whether the row existed.

    The learn step (P9-03) uses this to reinforce a near-duplicate memory (bump
    ``confidence``, refresh ``text``/``embedding``) and to demote a memory a later thumb-down
    disowned (lower ``confidence``). Only the provided fields are changed. Does not commit —
    the caller owns the transaction, matching the other primitives here. ``embedding`` must be
    re-supplied whenever ``text`` changes so the vector stays consistent with the text.
    """
    memory = await session.get(UserMemory, memory_id)
    if memory is None:
        return False
    if text is not None:
        memory.text = text
    if embedding is not None:
        memory.embedding = list(embedding)
    if confidence is not None:
        memory.confidence = confidence
    await session.flush()
    return True


async def delete_user_memory(
    session: AsyncSession,
    *,
    memory_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> bool:
    """Delete a ``user_memories`` row; return whether a matching row existed.

    Used by the learn step (P9-03) to remove a memory whose confidence a thumb-down drove to
    the floor, and by the memory-CRUD API (P9-05). Does not commit — caller-owned txn.

    ``user_id`` scopes the delete to one owner: when provided, a row that exists but belongs to
    another user returns ``False`` (indistinguishable from "unknown id" — the router maps both to
    ``404`` with no ownership leak, §7 AuthZ). The learn step, which already knows ownership via
    source-message attribution, omits it and deletes by id alone.
    """
    memory = await session.get(UserMemory, memory_id)
    if memory is None:
        return False
    if user_id is not None and memory.user_id != user_id:
        return False
    await session.delete(memory)
    await session.flush()
    return True


async def list_user_memories(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int = 200,
) -> list[UserMemoryListItem]:
    """List one user's memories, newest first (embedding column excluded) — the panel read.

    A plain (non-vector) ``SELECT ... WHERE user_id = :uid ORDER BY created_at DESC`` — a full
    listing needs no query embedding (contrast :func:`search_user_memories`, which is the
    per-turn similarity recall). ``limit`` bounds the result for a pathological account; a real
    user's learned memories are few. Does not commit — read-only, caller-owned session.
    """
    stmt = (
        select(
            UserMemory.id.label("memory_id"),
            UserMemory.text.label("text"),
            UserMemory.memory_type.label("memory_type"),
            UserMemory.confidence.label("confidence"),
            UserMemory.created_at.label("created_at"),
        )
        .where(UserMemory.user_id == user_id)
        .order_by(UserMemory.created_at.desc(), UserMemory.id)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        UserMemoryListItem(
            memory_id=row.memory_id,
            text=row.text,
            memory_type=row.memory_type,
            confidence=float(row.confidence),
            created_at=row.created_at,
        )
        for row in rows
    ]


async def clear_user_memories(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Delete **all** of one user's learned memories; return how many rows were removed.

    The "forget everything you've learned about me" action (P9-05) — scoped to ``user_id``, so it
    never touches another user's rows and leaves the user's explicit ``preferences`` untouched
    (a separate, user-authored table). Does not commit — caller-owned txn.
    """
    result = await session.execute(delete(UserMemory).where(UserMemory.user_id == user_id))
    return type_cast("CursorResult[Any]", result).rowcount or 0


async def list_user_memories_by_source_message(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    source_message_id: str,
) -> list[UserMemoryRecord]:
    """List one user's memories learned from ``source_message_id`` (embedding column excluded).

    The attribution primitive the learn step's thumb-down pass uses: a memory whose
    ``source_message_id`` is a turn the user later disapproved is the one to demote/remove. A
    lightweight projection (no 4096-dim vector) because the demotion policy needs only the id
    and current confidence.
    """
    stmt = select(
        UserMemory.id.label("memory_id"),
        UserMemory.text.label("text"),
        UserMemory.memory_type.label("memory_type"),
        UserMemory.confidence.label("confidence"),
        UserMemory.source_message_id.label("source_message_id"),
        UserMemory.updated_at.label("updated_at"),
    ).where(
        UserMemory.user_id == user_id,
        UserMemory.source_message_id == source_message_id,
    )
    rows = (await session.execute(stmt)).all()
    return [
        UserMemoryRecord(
            memory_id=row.memory_id,
            text=row.text,
            memory_type=row.memory_type,
            confidence=float(row.confidence),
            source_message_id=row.source_message_id,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


async def hybrid_search_chunks(
    session: AsyncSession,
    *,
    query_embedding: Sequence[float],
    query_text: str,
    k: int,
    vector_weight: float = 0.5,
    text_weight: float = 0.5,
    rrf_k: int = DEFAULT_RRF_K,
    kb_document_ids: Sequence[uuid.UUID] | None = None,
) -> list[SearchResult]:
    """Weighted hybrid search over ``kb_chunks`` (cosine + ``ts_rank`` via RRF).

    Blends dense cosine similarity and lexical ``ts_rank`` using Reciprocal Rank Fusion with
    **caller-configurable** ``vector_weight`` / ``text_weight`` (see the module docstring for
    why RRF over a raw weighted sum). Results are ordered by the fused score, ``LIMIT k``.

    Args:
        query_embedding: The query vector (``EmbeddingClient.embed_query`` output).
        query_text: The raw query — fed to ``plainto_tsquery('english', ...)`` for the
            lexical half.
        k: Max results to return.
        vector_weight / text_weight: Relative influence of each ranker. Any non-negative
            floats (need not sum to 1); e.g. ``text_weight=1, vector_weight=0`` is pure
            lexical. Defaults 0.5 / 0.5.
        rrf_k: RRF smoothing constant (default :data:`DEFAULT_RRF_K`).
        kb_document_ids: Optional restriction to chunks of these documents.

    Returns:
        Up to ``k`` :class:`SearchResult`, best fused score first.
    """
    embedding = list(query_embedding)
    tsquery = func.plainto_tsquery("english", query_text)
    distance = KbChunk.embedding.cosine_distance(embedding)
    text_rank = func.ts_rank(KbChunk.content_tsv, tsquery)

    # Inner query: raw signals + each row's rank on each signal (window functions).
    inner = select(
        KbChunk.id.label("chunk_id"),
        KbChunk.kb_document_id.label("kb_document_id"),
        KbChunk.content.label("content"),
        KbChunk.meta.label("meta"),
        (1.0 - distance).label("vector_similarity"),
        text_rank.label("text_rank"),
        func.rank().over(order_by=distance.asc()).label("vector_rank"),
        func.rank().over(order_by=text_rank.desc()).label("text_rank_pos"),
    )
    if kb_document_ids is not None:
        inner = inner.where(KbChunk.kb_document_id.in_(list(kb_document_ids)))
    sub = inner.subquery()

    # RRF fusion of the two ranks with the caller's weights. cast → float so the numeric
    # division stays floating-point regardless of driver typing.
    score = (
        vector_weight * (1.0 / cast(rrf_k + sub.c.vector_rank, Float))
        + text_weight * (1.0 / cast(rrf_k + sub.c.text_rank_pos, Float))
    ).label("score")

    stmt = (
        select(
            sub.c.chunk_id,
            sub.c.kb_document_id,
            sub.c.content,
            sub.c.meta,
            sub.c.vector_similarity,
            sub.c.text_rank,
            score,
        )
        .order_by(score.desc())
        .limit(k)
    )

    rows = (await session.execute(stmt)).all()
    return [
        SearchResult(
            chunk_id=row.chunk_id,
            kb_document_id=row.kb_document_id,
            content=row.content,
            score=float(row.score),
            vector_similarity=float(row.vector_similarity),
            text_rank=float(row.text_rank),
            meta=row.meta or {},
        )
        for row in rows
    ]


async def hybrid_search(
    session: AsyncSession,
    embedder: EmbeddingClient,
    query: str,
    *,
    k: int = 5,
    vector_weight: float = 0.5,
    text_weight: float = 0.5,
    rrf_k: int = DEFAULT_RRF_K,
    kb_document_ids: Sequence[uuid.UUID] | None = None,
) -> list[SearchResult]:
    """Embed ``query`` via ``embedder`` then :func:`hybrid_search_chunks` — the full primitive.

    Thin composition of the LLM-layer :class:`~app.llm.embeddings.EmbeddingClient` interface
    (injected, not constructed here) and the DB search above. The embedder is only
    duck-typed (``embed_query``); the RAG service (P4/P5) is what will own wiring a concrete
    client to this call.
    """
    query_embedding = await embedder.embed_query(query)
    return await hybrid_search_chunks(
        session,
        query_embedding=query_embedding,
        query_text=query,
        k=k,
        vector_weight=vector_weight,
        text_weight=text_weight,
        rrf_k=rrf_k,
        kb_document_ids=kb_document_ids,
    )


async def search_user_memories(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    query_embedding: Sequence[float],
    k: int = 5,
) -> list[MemorySearchResult]:
    """Vector-only cosine-similarity search over one user's ``user_memories`` (§4/§5.4).

    **Not hybrid** by design: ``user_memories`` has no lexical (``tsvector``) column in P2-04
    — LangMem recalls memories by semantic proximity to the current turn, not lexical match —
    so there is no lexical signal to blend. Returns the ``k`` nearest by cosine distance.
    """
    distance = UserMemory.embedding.cosine_distance(list(query_embedding))
    stmt = (
        select(
            UserMemory.id.label("memory_id"),
            UserMemory.text.label("text"),
            (1.0 - distance).label("similarity"),
            UserMemory.memory_type.label("memory_type"),
            UserMemory.confidence.label("confidence"),
        )
        .where(UserMemory.user_id == user_id)
        .order_by(distance.asc())
        .limit(k)
    )
    rows = (await session.execute(stmt)).all()
    return [
        MemorySearchResult(
            memory_id=row.memory_id,
            text=row.text,
            similarity=float(row.similarity),
            memory_type=row.memory_type,
            confidence=float(row.confidence),
        )
        for row in rows
    ]
