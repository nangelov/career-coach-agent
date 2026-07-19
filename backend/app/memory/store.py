"""Per-user teachable-memory store over the pgvector ``user_memories`` table (§5.4 / §6.7).

This is the **single home** for vector access to ``user_memories`` — the store that
**LangMem** manages recall/learn over (design §6.7: *"memory vectors continue to live in our
pgvector ``user_memories`` table where LangMem supports a pgvector-backed store"*). Rather
than let LangGraph's own Postgres store create/manage a **parallel** schema, this adapter
conforms to :class:`langgraph.store.base.BaseStore` over the schema P2-04 already migrated,
namespaced per user as ``("memories", "<user_id>")``.

**Recall (P9-02): similarity search.** The store exposes a typed, first-party
:meth:`search_memories` (embed the turn → cosine top-k over one user's memories) that the
pre-planner recall node (:mod:`app.agents.memory_agent`) calls directly, plus a
:class:`BaseStore`-conforming :meth:`abatch` that services :class:`~langgraph.store.base.SearchOp`
so LangMem's memory tooling can drive the same search.

**Learn/write (P9-03): typed methods.** The write path is the first-party
:meth:`add_memory` / :meth:`update_memory` / :meth:`delete_memory` /
:meth:`list_memories_for_message` (each wraps a :mod:`app.repositories.vector_search` primitive
and owns its commit), which the post-turn learn step (:mod:`app.tasks.memory_learn`) drives and
the memory-CRUD API (P9-05) will reuse. The generic :class:`~langgraph.store.base.PutOp` /
``DeleteOp`` / ``GetOp`` are **not** serviced by :meth:`abatch` — memories are addressed by the
typed methods, so wiring the generic ops would be unused surface — and still raise there so the
boundary stays explicit.

**Fail-soft is the caller's job, not the store's.** :meth:`search_memories` propagates DB/embedding
errors; the recall node wraps them and degrades to an empty context (the same posture the RAG
worker holds), so the store stays a thin, honest data-access seam.

**Dependency injection (mirrors the RAG worker, P4-04).** The store takes an
:class:`~app.llm.embeddings.EmbeddingClient` and the shared-pool :class:`SessionProvider`
capability by keyword — it never constructs an embedding path or a pool itself.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from langgraph.store.base import BaseStore, Op, Result, SearchItem, SearchOp

from app.repositories.vector_search import (
    MemorySearchResult,
    UserMemoryListItem,
    UserMemoryRecord,
    add_user_memory,
    clear_user_memories,
    delete_user_memory,
    list_user_memories,
    list_user_memories_by_source_message,
    search_user_memories,
    update_user_memory,
)

if TYPE_CHECKING:
    # Imported under TYPE_CHECKING (only an annotation below): importing
    # ``app.agents.rag_agent`` at runtime pulls in the ``app.agents`` package, which imports
    # ``app.agents.memory_agent`` → back into this module — a cycle that breaks whenever
    # ``app.memory`` is imported before ``app.agents`` (e.g. via the learn task).
    # ``SessionProvider`` is structural, used only for typing here, so a deferred import suffices.
    from app.agents.rag_agent import SessionProvider
    from app.llm.embeddings import EmbeddingClient

__all__ = [
    "DEFAULT_MEMORY_K",
    "MEMORY_NAMESPACE_PREFIX",
    "UserMemoryStore",
    "memory_namespace",
]

#: Top of the per-user namespace: ``("memories", "<user_id>")``. A single, stable prefix so the
#: learn step (P9-03) and the CRUD API (P9-05) address the same rows this recall step reads.
MEMORY_NAMESPACE_PREFIX = "memories"

#: How many memories recall pulls per turn (design §5.4 "top-k relevant ``user_memories``").
DEFAULT_MEMORY_K = 5


def memory_namespace(user_id: uuid.UUID | str) -> tuple[str, str]:
    """The LangGraph store namespace for one user's memories: ``("memories", "<user_id>")``."""
    return (MEMORY_NAMESPACE_PREFIX, str(user_id))


class UserMemoryStore(BaseStore):
    """A :class:`BaseStore`-conforming adapter over one schema of ``user_memories`` (§6.7).

    Namespaced per user (:func:`memory_namespace`). This task wires only **similarity search**
    (recall); the write path (put/update/delete) is filled in by the learn step (P9-03) and the
    memory-CRUD API (P9-05), which subclass/extend this store. Search is served two ways that
    share one query path:

    * :meth:`search_memories` — the typed, first-party entrypoint the recall node uses (returns
      :class:`~app.repositories.vector_search.MemorySearchResult` rows).
    * :meth:`abatch` — the :class:`BaseStore` async contract; it services
      :class:`~langgraph.store.base.SearchOp` (so LangMem tooling can drive recall) and raises
      for every other op (see class-level scope note).

    The synchronous :meth:`batch` is unsupported: the graph and the Celery learn job are async.
    """

    #: This store has no TTL semantics (memories persist until the user/learn step deletes them).
    supports_ttl = False

    def __init__(
        self,
        *,
        embedder: EmbeddingClient,
        db: SessionProvider,
        k: int = DEFAULT_MEMORY_K,
    ) -> None:
        self._embedder = embedder
        self._db = db
        self._k = k

    async def search_memories(
        self,
        user_id: uuid.UUID,
        query: str,
        *,
        k: int | None = None,
    ) -> list[MemorySearchResult]:
        """Cosine top-k of ``user_id``'s memories most similar to ``query`` (design §5.4).

        Embeds ``query`` with the injected :class:`~app.llm.embeddings.EmbeddingClient` and runs
        the P2-06 :func:`~app.repositories.vector_search.search_user_memories` primitive (no
        hand-rolled pgvector query). A blank query short-circuits to no results. Propagates any
        DB/embedding error — the recall node is what degrades to an empty context.
        """
        cleaned = query.strip()
        if not cleaned:
            return []
        query_embedding = await self._embedder.embed_query(cleaned)
        async with self._db.session() as session:
            return await search_user_memories(
                session,
                user_id=user_id,
                query_embedding=query_embedding,
                k=k if k is not None else self._k,
            )

    async def add_memory(
        self,
        user_id: uuid.UUID,
        text: str,
        *,
        memory_type: str,
        confidence: float,
        source_message_id: str | None = None,
    ) -> uuid.UUID:
        """Embed and insert a new learned memory for ``user_id``; return its id (P9-03).

        The typed write entrypoint the learn step uses (no hand-rolled SQL in the task layer):
        embeds ``text`` with the injected :class:`~app.llm.embeddings.EmbeddingClient` and
        inserts via the P2-06 :func:`~app.repositories.vector_search.add_user_memory` primitive,
        committing the single-row transaction. ``memory_type`` must be a check-constraint value
        (``preference`` / ``fact`` / ``style``); ``source_message_id`` links the memory to the
        turn it was learned from (§5.5) so a later thumb-down can attribute and demote it.
        """
        embedding = await self._embedder.embed_query(text)
        async with self._db.session() as session:
            memory = await add_user_memory(
                session,
                user_id=user_id,
                text=text,
                embedding=embedding,
                memory_type=memory_type,
                confidence=confidence,
                source_message_id=source_message_id,
            )
            await session.commit()
            return memory.id

    async def update_memory(
        self,
        memory_id: uuid.UUID,
        *,
        text: str | None = None,
        confidence: float | None = None,
    ) -> bool:
        """Update a memory's ``text`` and/or ``confidence`` in place; return whether it existed.

        Used by the learn step to reinforce a near-duplicate (bump confidence, refresh text) and
        to demote a thumb-downed memory (lower confidence). When ``text`` changes it is re-embedded
        so the vector stays consistent with the text. Commits the transaction.
        """
        embedding = await self._embedder.embed_query(text) if text is not None else None
        async with self._db.session() as session:
            updated = await update_user_memory(
                session,
                memory_id=memory_id,
                text=text,
                embedding=embedding,
                confidence=confidence,
            )
            await session.commit()
            return updated

    async def delete_memory(self, memory_id: uuid.UUID) -> bool:
        """Delete a memory by id; return whether it existed. Commits the transaction (P9-03).

        Unscoped by design — the learn step already knows ownership via source-message
        attribution. The user-facing memory panel (P9-05) uses :meth:`delete_memory_for_user`
        instead, which enforces caller ownership.
        """
        async with self._db.session() as session:
            deleted = await delete_user_memory(session, memory_id=memory_id)
            await session.commit()
            return deleted

    async def delete_memory_for_user(self, memory_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Delete one of ``user_id``'s memories; return ``False`` if unknown or not theirs (P9-05).

        The ownership-scoped delete the memory panel uses: a memory id that exists but belongs to
        another user returns ``False`` (the router maps it to ``404`` with no ownership leak,
        mirroring ``dashboard``/``message_feedback``). Commits the transaction.
        """
        async with self._db.session() as session:
            deleted = await delete_user_memory(session, memory_id=memory_id, user_id=user_id)
            await session.commit()
            return deleted

    async def list_memories(self, user_id: uuid.UUID) -> list[UserMemoryListItem]:
        """List all of ``user_id``'s learned memories, newest first (embedding excluded) (P9-05).

        The panel read — a plain (non-vector) listing (contrast :meth:`search_memories`, the
        per-turn similarity recall). Read-only, so it does not open a write transaction.
        """
        async with self._db.session() as session:
            return await list_user_memories(session, user_id=user_id)

    async def clear_memories(self, user_id: uuid.UUID) -> int:
        """Delete **all** of ``user_id``'s learned memories; return the count removed (P9-05).

        The panel's "forget everything you've learned about me" action — scoped to the user and
        leaving their explicit ``preferences`` untouched. Commits the transaction.
        """
        async with self._db.session() as session:
            count = await clear_user_memories(session, user_id=user_id)
            await session.commit()
            return count

    async def list_memories_for_message(
        self, user_id: uuid.UUID, source_message_id: str
    ) -> list[UserMemoryRecord]:
        """List ``user_id``'s memories learned from ``source_message_id`` (thumb-down attribution).

        Read seam for the learn step's demotion pass — the memories a later-disapproved turn
        produced. Read-only, so it does not open a write transaction.
        """
        async with self._db.session() as session:
            return await list_user_memories_by_source_message(
                session, user_id=user_id, source_message_id=source_message_id
            )

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        """Service the :class:`BaseStore` async op batch — :class:`SearchOp` only (P9-02).

        Each :class:`~langgraph.store.base.SearchOp` is resolved against one user's memories
        (namespace ``("memories", "<user_id>")``) and mapped to :class:`SearchItem`. The write
        path is exposed as the **typed, first-party** methods above (:meth:`add_memory` /
        :meth:`update_memory` / :meth:`delete_memory`), which the learn step (P9-03) drives —
        not through :class:`~langgraph.store.base.PutOp`/``DeleteOp``. Those (and get/list) still
        raise here: the graph and learn job address memories by the typed methods, so servicing
        the generic ops would be unused surface (YAGNI). The memory-CRUD API (P9-05) reuses the
        typed methods too.
        """
        results: list[Result] = []
        for op in ops:
            if isinstance(op, SearchOp):
                results.append(await self._run_search_op(op))
            else:
                raise NotImplementedError(
                    f"{type(self).__name__} services SearchOp only (recall, P9-02); "
                    f"{type(op).__name__} (put/get/list) is owned by the learn step (P9-03) "
                    "and the memory-CRUD API (P9-05)."
                )
        return results

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        """Unsupported — the store is async-only (the graph + the Celery learn job). Use
        :meth:`abatch`."""
        raise NotImplementedError(
            f"{type(self).__name__} is async-only (graph + Celery); use abatch()."
        )

    async def _run_search_op(self, op: SearchOp) -> list[SearchItem]:
        """Map a :class:`SearchOp` over one user's memories to :class:`SearchItem` results.

        The user is taken from the op's namespace prefix; a namespace that is not a
        ``("memories", "<uuid>")`` handle (or a missing query) yields no results. ``created_at`` /
        ``updated_at`` are stamped ``now`` — the cosine search projection does not carry per-row
        timestamps, and LangMem recall keys on the item value + score, not on these.
        """
        user_uuid = _user_id_from_namespace(op.namespace_prefix)
        if user_uuid is None or not op.query:
            return []
        hits = await self.search_memories(user_uuid, op.query, k=op.limit or self._k)
        now = datetime.now(UTC)
        return [
            SearchItem(
                namespace=memory_namespace(user_uuid),
                key=str(hit.memory_id),
                value={
                    "text": hit.text,
                    "memory_type": hit.memory_type,
                    "confidence": hit.confidence,
                },
                created_at=now,
                updated_at=now,
                score=hit.similarity,
            )
            for hit in hits
        ]


def _user_id_from_namespace(namespace: tuple[str, ...]) -> uuid.UUID | None:
    """Extract the user UUID from a ``("memories", "<user_id>")`` namespace (or ``None``)."""
    if len(namespace) >= 2 and namespace[0] == MEMORY_NAMESPACE_PREFIX:
        candidate = namespace[-1]
    elif len(namespace) == 1:
        candidate = namespace[0]
    else:
        return None
    try:
        return uuid.UUID(candidate)
    except (ValueError, TypeError):
        return None
