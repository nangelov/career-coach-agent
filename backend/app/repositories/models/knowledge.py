"""Knowledge-base & vector ORM models (design §4 — Postgres + pgvector).

The second real table group of the v2 schema (P2-04). Every class subclasses the
shared :class:`~app.repositories.postgres.Base` so they land on the one ``metadata``
Alembic autogenerates from and the repository layer queries through.

Three tables live here (design §4 *"Postgres + pgvector — knowledge, memory &
structured records"*):

* :class:`KbDocument` — RAG knowledge-base source documents: curated career/learning
  content (``user_id`` NULL → shared) and a user's own parsed CV (``user_id`` set,
  ``source_type = 'user_cv'``, §5.1).
* :class:`KbChunk` — the retrieval unit: one embedded text chunk of a document, carrying
  the **``vector(4096)``** embedding (dimension fixed by ``Qwen/Qwen3-Embedding-8B``,
  §6 item 3) *and* a generated ``tsvector`` for lexical search.
* :class:`UserMemory` — teachable per-user memory (§5.4/§5.5): a learned fact + its
  embedding, the store **LangMem** manages in P9. Schema-only here.

Design constraints baked into the schema:

* **Fixed embedding dimension = 4096 (§6 item 3).** Both ``embedding`` columns are
  :class:`pgvector.sqlalchemy.Vector` of exactly 4096 — the full (non-truncated)
  ``Qwen/Qwen3-Embedding-8B`` output. Do not vary this without a deliberate migration.
* **Cosine similarity + high-dimension ANN index (§6, P2 exit criterion).** The
  embedding is 4096-dim, which **exceeds pgvector's ANN-index dimension caps** — HNSW
  supports at most 2000 dims for ``vector`` and 4000 for ``halfvec``. So a plain
  ``vector_cosine_ops`` HNSW index is *impossible* at 4096 without truncating the locked
  dimension (§6 forbids that here). The pgvector-documented pattern for >4000-dim vectors
  is used instead: an HNSW index over the **binary quantization** of the embedding
  (``(binary_quantize(embedding)::bit(4096)) bit_hamming_ops`` — ``bit`` supports up to
  64000 dims). This accelerates candidate retrieval; the full-precision ``vector(4096)``
  column is kept for **exact cosine** distance (``ORDER BY embedding <=> :q``), which is
  what the P2 exit-criterion query uses directly and what a later hybrid search reranks
  on. HNSW (not IVFFlat) needs no training data — correct for tables that start empty.
  These functional indexes are created in the migration via raw SQL (a
  ``binary_quantize(...)::bit(...)`` expression index is not expressible through
  ``mapped_column``); they are intentionally **not** in ``__table_args__``. See the
  P2-04 ``engineer.md`` "Key decisions" for the flag raised to the architect.
* **Hybrid search is anticipated, not implemented here.** :attr:`KbChunk.content_tsv`
  is a Postgres ``GENERATED ALWAYS AS (to_tsvector('english', content)) STORED`` column
  with a **GIN** index, so a later weighted blend of ``1 - cosine_distance`` and
  ``ts_rank`` (the ``llm/embeddings.py`` task) has both index types ready — this task
  only guarantees the schema does not block it.
* **GDPR-delete posture (§4).** Deleting a user cascades to their private
  :class:`KbDocument` rows (and thence their chunks) and to all their
  :class:`UserMemory` rows — user-scoped, user-viewable/deletable per §5.4. Shared
  curated KB documents have ``user_id`` NULL and are unaffected by any single
  user-delete.

Note on the ``metadata`` column: SQLAlchemy reserves the ``metadata`` *attribute* name
on the declarative base, so the Python attributes are named ``meta`` while the underlying
column is explicitly named ``"metadata"`` (matching the design's ``metadata JSONB``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.repositories.models._mixins import CreatedAtMixin
from app.repositories.postgres import Base

#: Embedding dimension — fixed by ``Qwen/Qwen3-Embedding-8B`` full output (§6 item 3).
#: Both ``kb_chunks.embedding`` and ``user_memories.embedding`` use exactly this width.
EMBEDDING_DIM = 4096

#: Provenance of a KB document. Curated = shared career/learning content (``user_id``
#: NULL); ``user_cv`` = a user's parsed CV (§5.1); ``crawled`` = fetched web content.
_SOURCE_TYPE_VALUES = ("curated", "user_cv", "crawled")
#: Kind of learned memory (§5.4) — an explicit preference, a durable fact, or a
#: communication-style signal.
_MEMORY_TYPE_VALUES = ("preference", "fact", "style")


class KbDocument(CreatedAtMixin, Base):
    """A RAG knowledge-base source document (§4/§5.1).

    Holds curated career/learning content (shared: ``user_id`` NULL) or a user's own
    parsed CV (private: ``user_id`` set, ``source_type = 'user_cv'``). The retrievable
    text lives in the child :class:`KbChunk` rows; :attr:`content` keeps the *raw* source
    text optionally (see the class decision below).
    """

    __tablename__ = "kb_documents"
    __table_args__ = (
        CheckConstraint(
            f"source_type IN ({', '.join(repr(v) for v in _SOURCE_TYPE_VALUES)})",
            name="ck_kb_documents_source_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # e.g. a source URL, a curated-content id, or the literal "user-cv".
    source: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # NULL → shared/curated KB content; set → a single user's private (CV-derived) doc.
    # Cascades so a GDPR user-delete removes the user's private documents (and, via the
    # chunks relationship, their chunks). Shared docs (NULL) are untouched.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Raw source text. NULLABLE by design: large documents may be stored chunk-only
    # (the retrievable text lives in kb_chunks.content); keeping the raw blob here is
    # optional and left to the ingestion layer.
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Python attr ``meta`` → DB column "metadata" (``metadata`` is reserved on Base).
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    chunks: Mapped[list[KbChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KbChunk(CreatedAtMixin, Base):
    """One embedded, retrievable chunk of a :class:`KbDocument` (§4).

    This is the unit similarity search returns. It carries the ``vector(4096)`` embedding
    (§6 item 3) for vector search **and** a generated ``tsvector`` (:attr:`content_tsv`)
    for lexical/full-text search — the two signals a later weighted hybrid query blends.
    """

    __tablename__ = "kb_chunks"
    __table_args__ = (
        # GIN over the generated tsvector → index-backed full-text ranking for the
        # lexical half of the future hybrid search. (The vector ANN index is a
        # binary-quantize functional index created in the migration via raw SQL — see
        # the module docstring — because 4096 dims exceed pgvector's HNSW cap for the
        # ``vector``/``halfvec`` types.)
        Index(
            "ix_kb_chunks_content_tsv",
            "content_tsv",
            postgresql_using="gin",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    kb_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kb_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Ordering of this chunk within its parent document (0-based).
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    # Generated, STORED tsvector of ``content`` — maintained by Postgres, never written
    # by the app; read-only from the ORM's perspective.
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
        nullable=False,
    )
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )

    document: Mapped[KbDocument] = relationship(back_populates="chunks")


class UserMemory(CreatedAtMixin, Base):
    """A teachable per-user memory (§5.4/§5.5) — a learned fact + its embedding.

    Retrieved by cosine similarity to the current turn each request; **LangMem** owns
    recall/learn/dedup over this table in P9 (§6.7). This task is schema-only. Cascades
    on user-delete (user-scoped, user-viewable/deletable — §4 GDPR posture).
    """

    __tablename__ = "user_memories"
    __table_args__ = (
        CheckConstraint(
            f"memory_type IN ({', '.join(repr(v) for v in _MEMORY_TYPE_VALUES)})",
            name="ck_user_memories_memory_type",
        ),
        # The vector ANN index (binary-quantize HNSW) is created in the migration via raw
        # SQL — see the module docstring — because 4096 dims exceed pgvector's HNSW cap.
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The learned fact/preference, in natural language.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.0")
    # The turn this memory was learned from (§5.5). References the stable app-level
    # ``messages.message_id``, not the surrogate PK. SET NULL (not CASCADE): if that one
    # message is pruned, the learned memory survives detached rather than being erased —
    # a user-delete still removes the memory via the ``user_id`` cascade above.
    source_message_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("messages.message_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
