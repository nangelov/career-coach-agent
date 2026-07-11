"""RAG worker — embed the turn, retrieve from the pgvector KB, cite (design §3).

This replaces the P4-02 ``rag_node`` stub with the real *retrieval* worker described in
design §3 (*"RAG Agent: embed the query, retrieve grounded snippets from the pgvector
knowledge base (curated content + the user's parsed CV), return citations"*). Its job is
**retrieval + citation only** — it does *not* call the LLM to compose an answer; that
synthesis is the responder's job (P4-05/06). This worker hands the responder grounded
material (top-k excerpts) plus per-chunk :class:`~app.agents.state.Citation` provenance.

**What it does, in order.**

1. Take the current turn's ``user_message`` as the query (design keeps this simple — the
   turn text is enough grounding signal; recent history is already the planner's concern).
2. Resolve the **access-scoped** set of ``kb_documents`` the turn may see and pass those
   document ids to the retrieval primitive.
3. Embed the query and hybrid-search ``kb_chunks`` via the P2-06
   :func:`~app.repositories.vector_search.hybrid_search` primitive (weighted RRF of cosine
   + ``ts_rank``) — this worker does **not** hand-roll a pgvector query.
4. Map each :class:`~app.repositories.vector_search.SearchResult` to a
   :class:`~app.agents.state.Citation` and bundle the excerpts into
   :attr:`~app.agents.state.WorkerResult.content`.

**Access scoping (acceptance criterion / §4 ownership).** ``kb_documents.user_id IS NULL``
is the shared curated KB — always in scope. A logged-in user *also* sees their own private
CV-derived documents (``user_id = state.user_id``); a guest (``user_id`` unset) sees only
the shared KB and can never reach another user's private docs. Because
:func:`~app.repositories.vector_search.hybrid_search_chunks` filters by a ``kb_document_ids``
allow-list (not by ``user_id``), we resolve the allowed document-id set up front with one
small ``SELECT`` against ``kb_documents`` and pass it through — reusing the existing
primitive unchanged rather than extending it. We **always** pass an explicit id list (never
``None``, which would mean "no filter" and leak every user's private docs): an empty
allow-list simply yields no results. The curated KB is a bounded, curated corpus, so
materialising its ids is cheap; if it grows large the follow-up is to push the ownership
predicate into the search query (a repository change), noted but out of scope here.

**Fail-soft (a retrieval failure must not crash the turn).** Any embedding/DB error is
caught and returned as a :class:`~app.agents.state.WorkerResult` carrying an ``error`` and
empty citations — mirroring the planner's safe-default posture (P4-03). The responder can
still answer from other workers or a plain reply; a broken KB never 500s the graph.

**Dependency injection (test seam, mirrors P4-03).** :func:`retrieve` takes an
:class:`~app.llm.embeddings.EmbeddingClient` and a :class:`SessionProvider` (a structural
capability the shared :class:`~app.repositories.postgres.PostgresConnectionProvider`
satisfies) by keyword — never constructing an embedding path or a pool itself.
:func:`make_rag_node` binds them into a LangGraph node closure; ``build_graph`` wires
production singletons and unit tests inject fakes. The provider's ``session()`` context
manager (not the request-scoped ``get_db_session`` dependency) is what lets a graph node
acquire a session from the shared pool outside a FastAPI request.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from sqlalchemy import ColumnElement, or_, select

from app.agents.state import AgentState, Citation, WorkerName, WorkerResult
from app.repositories.models.knowledge import KbDocument
from app.repositories.vector_search import SearchResult, hybrid_search

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.llm.embeddings import EmbeddingClient

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_TOP_K", "SessionProvider", "make_rag_node", "retrieve"]


@runtime_checkable
class SessionProvider(Protocol):
    """The DB capability the RAG worker needs: hand out a pooled ``AsyncSession``.

    A structural :class:`~typing.Protocol` (not a hard import of
    :class:`~app.repositories.postgres.PostgresConnectionProvider`) so the worker depends on
    a *capability*, not a concrete class — the shared-pool provider satisfies it in
    production and unit tests inject a scripted fake. Mirrors the planner's ``LLMCompleter``
    seam (P4-03). Its :meth:`session` is the context manager that works outside a FastAPI
    request (unlike the ``get_db_session`` dependency), which a graph node needs.
    """

    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


#: How many chunks to retrieve for a turn (matches ``hybrid_search``'s own default k).
DEFAULT_TOP_K = 5
#: Max characters kept per citation snippet / bundled excerpt (keeps the responder's
#: context bounded; the full chunk is still addressable by ``source_id``).
SNIPPET_MAX_CHARS = 400


async def retrieve(
    state: AgentState,
    *,
    embedder: EmbeddingClient,
    db: SessionProvider,
    k: int = DEFAULT_TOP_K,
) -> WorkerResult:
    """Retrieve grounded KB snippets + citations for the current turn (design §3).

    Embeds ``state.user_message``, hybrid-searches the access-scoped ``kb_chunks``, and
    returns a :class:`WorkerResult` with a bundled-excerpt ``content`` and one
    :class:`Citation` per hit. Fails soft: any embedding/DB error yields a
    ``WorkerResult`` with ``error`` set and no citations (never raises out of the node).
    """
    query = state.user_message.strip()
    if not query:
        return WorkerResult(worker=WorkerName.RAG)

    try:
        async with db.session() as session:
            allowed_ids = await _allowed_document_ids(session, state.user_id)
            if not allowed_ids:
                # No shared KB and no private docs in scope → nothing to retrieve.
                return WorkerResult(worker=WorkerName.RAG)
            results = await hybrid_search(
                session, embedder, query, k=k, kb_document_ids=allowed_ids
            )
            titles = await _document_titles(session, {r.kb_document_id for r in results})
    except Exception as exc:
        logger.warning("RAG retrieval failed; returning empty result", exc_info=True)
        return WorkerResult(worker=WorkerName.RAG, error=f"retrieval failed: {exc}")

    if not results:
        return WorkerResult(worker=WorkerName.RAG)

    citations = [_to_citation(r, titles.get(r.kb_document_id)) for r in results]
    return WorkerResult(
        worker=WorkerName.RAG,
        content=_bundle_excerpts(results, titles),
        citations=citations,
        data={"chunk_count": len(results)},
    )


def make_rag_node(
    *,
    embedder: EmbeddingClient | None = None,
    db: SessionProvider | None = None,
    k: int = DEFAULT_TOP_K,
) -> Any:
    """Build the LangGraph ``rag`` node closure, binding its collaborators (P4-03 pattern).

    The returned coroutine is a LangGraph node: it runs :func:`retrieve` and adapts the
    :class:`WorkerResult` into the ``{"worker_results": ..., "citations": ...}`` partial
    update the graph's fan-in reducers (P4-01) fold in — the same shape the P4-02 stub
    produced.

    ``embedder`` defaults to the settings-configured in-process
    :class:`~app.llm.embeddings.SentenceTransformerEmbeddingClient` (lazy — no model load
    until first use). ``db`` has **no** eager default: the shared
    :class:`~app.repositories.postgres.PostgresConnectionProvider` is owned by the app
    lifespan (design §4 — a single shared pool) and is injected when the chat endpoint wires
    the graph (a later task). Until then the module-level graph's ``rag`` node fails soft if
    routed without a provider, rather than opening a second, rogue pool.
    """

    async def rag_node(state: AgentState) -> dict[str, Any]:
        if db is None:
            logger.warning(
                "RAG node routed without a DB provider; skipping retrieval "
                "(inject one via build_graph(db=...))"
            )
            return _node_update(
                WorkerResult(worker=WorkerName.RAG, error="rag worker not configured")
            )
        resolved_embedder = embedder or _default_embedder()
        result = await retrieve(state, embedder=resolved_embedder, db=db, k=k)
        return _node_update(result)

    return rag_node


def _node_update(result: WorkerResult) -> dict[str, Any]:
    """Adapt a :class:`WorkerResult` into the RAG node's partial state update.

    Writes the result under the RAG worker's own key (key-wise merge — no clobbering) and
    contributes its citations to the list-concatenated ``citations`` slice (P4-01 reducers).
    """
    return {
        "worker_results": {WorkerName.RAG.value: result},
        "citations": list(result.citations),
    }


async def _allowed_document_ids(session: AsyncSession, user_id: str | None) -> list[uuid.UUID]:
    """Resolve the ``kb_documents`` ids the turn may retrieve from (access scoping).

    Always includes the shared curated KB (``user_id IS NULL``); additionally includes a
    logged-in user's own private (CV-derived) documents. A guest — or a malformed user id —
    sees only the shared KB.
    """
    condition: ColumnElement[bool] = KbDocument.user_id.is_(None)
    user_uuid = _parse_user_uuid(user_id)
    if user_uuid is not None:
        condition = or_(condition, KbDocument.user_id == user_uuid)
    rows = await session.execute(select(KbDocument.id).where(condition))
    return list(rows.scalars().all())


async def _document_titles(session: AsyncSession, doc_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Look up parent-document titles for the retrieved chunks (one batched query)."""
    if not doc_ids:
        return {}
    rows = await session.execute(
        select(KbDocument.id, KbDocument.title).where(KbDocument.id.in_(doc_ids))
    )
    return {row.id: row.title for row in rows.all()}


def _parse_user_uuid(user_id: str | None) -> uuid.UUID | None:
    """Parse ``state.user_id`` to a UUID, or ``None`` (→ shared-KB-only) if unusable.

    ``AgentState.user_id`` is a ``str`` (or ``None`` for guests) while ``kb_documents.user_id``
    is a UUID. A non-UUID value cannot match any private doc, so we restrict to the shared KB
    rather than failing the whole retrieval.
    """
    if not user_id:
        return None
    try:
        return uuid.UUID(user_id)
    except ValueError:
        logger.warning("RAG: user_id is not a valid UUID; restricting to shared KB only")
        return None


def _to_citation(result: SearchResult, title: str | None) -> Citation:
    """Map one :class:`SearchResult` to a :class:`Citation` (design §3 provenance)."""
    return Citation(
        source_id=str(result.chunk_id),
        title=title,
        snippet=_truncate(result.content),
        worker=WorkerName.RAG,
    )


def _bundle_excerpts(results: Sequence[SearchResult], titles: dict[uuid.UUID, str]) -> str:
    """Concatenate the top-k excerpts into one grounded snippet bundle for the responder.

    Numbered so the responder can reference sources ``[1]``, ``[2]`` … alongside the parallel
    :class:`Citation` list. This is grounding material, **not** a composed answer.
    """
    lines = [
        f"[{i}] {titles.get(r.kb_document_id) or 'Untitled source'}: {_truncate(r.content)}"
        for i, r in enumerate(results, start=1)
    ]
    return "\n\n".join(lines)


def _truncate(text: str, limit: int = SNIPPET_MAX_CHARS) -> str:
    """Trim ``text`` to ``limit`` chars on a whitespace-friendly boundary with an ellipsis."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _default_embedder() -> EmbeddingClient:
    """Lazily build the settings-configured in-process embedder (no model load until use).

    Deferred import keeps this module free of the ML stack at import time (CI installs only
    the curated light deps); constructing the client triggers **no** model download.
    """
    from app.llm.embeddings import SentenceTransformerEmbeddingClient

    return SentenceTransformerEmbeddingClient()
