"""Pre-planner memory recall worker (P9-02, design §3 "Memory recall" → §5.4).

Replaces the P4-02 ``memory_recall_node`` stub with the **real** recall step design §5.4
point 1 prescribes: *"fetch explicit prefs + top-k relevant ``user_memories`` → inject into
planner/responder context"*. It runs once, before the planner, and populates
:class:`~app.agents.state.MemoryContext` on the shared state:

* :attr:`~app.agents.state.MemoryContext.preferences` — the user's **explicit**, editable
  personalization settings, read from the ``preferences.data`` JSONB (§5.4 — the authoritative
  signal that overrides inferred memory);
* :attr:`~app.agents.state.MemoryContext.memories` — the **top-k learned** memories most
  similar to this turn, via the :class:`~app.memory.store.UserMemoryStore` (LangMem's
  pgvector-backed store, §6.7).

**Logged-in → durable; guest → ephemeral (P9-07).** Durable recall requires ``state.user_id`` (a
real ``users.id``) and reads Postgres. A **guest** (``user_id is None``) instead reads the
Redis-only :class:`~app.services.guest_memory.GuestMemory` store keyed by ``session_id`` (§5.4 —
"personalization is session-only for guests"), yielding the **same** :class:`MemoryContext` shape,
so the responder (P9-06) needs no change. When no guest store is wired the guest simply gets the
default-empty context (this node must never crash for them).

**Fail-soft (a recall failure must not crash the turn).** Any DB/embedding error degrades to
an empty :class:`MemoryContext` — the same posture as the RAG/market workers (P4-04/P6-04): a
broken memory read never 500s the graph, planning just proceeds without personalization.

**Dependency injection (mirrors the RAG worker, P4-04).** :func:`recall` takes the
:class:`~app.memory.store.UserMemoryStore` and the :class:`SessionProvider` by keyword;
:func:`make_memory_recall_node` binds them into a LangGraph node closure. ``build_graph`` wires
the production singletons (the same shared embedder + Postgres pool the RAG worker uses); unit
tests inject fakes. This node only makes the context **available** on the state — the
responder's tone/depth adaptation that consumes it is P9-06.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.agents.rag_agent import SessionProvider
from app.agents.state import AgentState, MemoryContext
from app.memory.store import DEFAULT_MEMORY_K, UserMemoryStore
from app.repositories.models.identity import Preference

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.llm.embeddings import EmbeddingClient
    from app.services.guest_memory import GuestMemory

logger = logging.getLogger(__name__)

__all__ = ["make_memory_recall_node", "recall"]


async def recall(
    state: AgentState,
    *,
    store: UserMemoryStore | None = None,
    db: SessionProvider | None = None,
    guest_memory: GuestMemory | None = None,
    k: int = DEFAULT_MEMORY_K,
) -> MemoryContext:
    """Recall explicit prefs + relevant memories into a context (design §5.4).

    A **guest** (``user_id`` unset) reads the Redis-only ``guest_memory`` store (P9-07); a
    **logged-in** user reads ``preferences.data`` + the ``k`` most similar ``user_memories`` to
    ``state.user_message``. Both fail soft — **any** store/DB/embedding error yields an empty
    :class:`MemoryContext` (never raises out of the node) — and both return the same shape.
    """
    user_uuid = _parse_user_uuid(state.user_id)
    if user_uuid is None:
        return await _recall_guest(state, guest_memory)

    if store is None or db is None:
        return MemoryContext()
    try:
        async with db.session() as session:
            preferences = await _fetch_preferences(session, user_uuid)
        hits = await store.search_memories(user_uuid, state.user_message, k=k)
        memories = [hit.text for hit in hits]
    except Exception:
        logger.warning("Memory recall failed; proceeding with empty context", exc_info=True)
        return MemoryContext()

    return MemoryContext(preferences=preferences, memories=memories)


async def _recall_guest(state: AgentState, guest_memory: GuestMemory | None) -> MemoryContext:
    """Read a guest's Redis-only, session-scoped personalization into a context (P9-07, §5.4).

    Returns the default-empty context when no guest store is wired or the guest has none; fails
    soft on any Redis error (the guest turn proceeds without personalization, never crashes).
    """
    if guest_memory is None or not state.session_id:
        return MemoryContext()
    try:
        personalization = await guest_memory.load(state.session_id)
    except Exception:
        logger.warning("Guest memory recall failed; proceeding with empty context", exc_info=True)
        return MemoryContext()
    return MemoryContext(
        preferences=personalization.preferences,
        memories=list(personalization.memories),
    )


def make_memory_recall_node(
    *,
    store: UserMemoryStore | None = None,
    embedder: EmbeddingClient | None = None,
    db: SessionProvider | None = None,
    guest_memory: GuestMemory | None = None,
    k: int = DEFAULT_MEMORY_K,
) -> Any:
    """Build the LangGraph ``memory_recall`` node closure, binding collaborators (P4-04 pattern).

    The returned coroutine runs :func:`recall` and writes the ``{"memory": MemoryContext}``
    partial update the planner/responder read (single writer — no reducer needed).

    Resolution mirrors the RAG worker: with **neither** ``db`` nor ``guest_memory`` bound (the
    import-time module default) the node is a no-op that leaves the default-empty
    :class:`MemoryContext` in place — so the module-level graph still compiles and non-recall unit
    tests are unaffected. ``build_graph`` binds the shared Postgres pool (``db=``) + in-process
    embedder (``embedder=``) for the durable path and the Redis ``guest_memory`` store for the
    guest path; an explicit ``store`` (tests) takes precedence over building one. A durable store is
    only built when ``db`` is given; the guest path needs only ``guest_memory``.
    """
    if db is None and guest_memory is None:
        # Sync (not async) on purpose: memory recall *always* runs (unlike the conditionally
        # routed workers), so the no-provider default must keep the import-time module graph
        # synchronously invokable — it just leaves the default-empty MemoryContext in place.
        def unbound_recall_node(state: AgentState) -> dict[str, Any]:
            return {}

        return unbound_recall_node

    resolved_store = store
    if resolved_store is None and db is not None:
        resolved_store = UserMemoryStore(embedder=embedder or _default_embedder(), db=db, k=k)

    async def memory_recall_node(state: AgentState) -> dict[str, Any]:
        return {
            "memory": await recall(
                state, store=resolved_store, db=db, guest_memory=guest_memory, k=k
            )
        }

    return memory_recall_node


async def _fetch_preferences(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Read the user's explicit ``preferences.data`` JSONB (one row per user), or ``{}``."""
    row = await session.execute(select(Preference.data).where(Preference.user_id == user_id))
    data = row.scalar_one_or_none()
    return data or {}


def _parse_user_uuid(user_id: str | None) -> uuid.UUID | None:
    """Parse ``state.user_id`` to a UUID, or ``None`` (guest / malformed → no durable recall).

    ``AgentState.user_id`` is a ``str`` (or ``None`` for guests) while ``users.id`` is a UUID; a
    non-UUID value cannot own any memory/preference row, so recall is skipped rather than failed.
    """
    if not user_id:
        return None
    try:
        return uuid.UUID(user_id)
    except ValueError:
        logger.warning("Memory recall: user_id is not a valid UUID; skipping recall")
        return None


def _default_embedder() -> EmbeddingClient:
    """Lazily build the settings-configured in-process embedder (no model load until use).

    Deferred import keeps this module free of the ML stack at import time (CI installs only the
    curated light deps); constructing the client triggers **no** model download.
    """
    from app.llm.embeddings import SentenceTransformerEmbeddingClient  # noqa: PLC0415

    return SentenceTransformerEmbeddingClient()
