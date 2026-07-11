"""Unit + integration tests for the RAG retrieval worker (P4-04, design §3).

Covers the acceptance criteria:

* the turn is embedded and the hybrid search is invoked with the expected args (the query
  vector, the query text, ``k`` and the access-scoped ``kb_document_ids``),
* each :class:`~app.repositories.vector_search.SearchResult` maps to a
  :class:`~app.agents.state.Citation` (source id / title / snippet / worker) and the excerpts
  bundle into ``WorkerResult.content``,
* access scoping — guests see only the shared curated KB; a logged-in user also sees their
  own private docs,
* the empty-results and no-documents-in-scope cases are handled, and the error path fails
  soft (a ``WorkerResult.error``, never an exception out of the node), and
* an integration test running the **real compiled graph** proves a RAG-routed turn ends up
  with ``AgentState.citations`` / ``worker_results['rag']`` populated end-to-end.

Neither the real 8B embedder nor a live pgvector DB is used: an ``EmbeddingClient`` double
returns a fixed vector and a scripted async session/provider (``tests.fakes``) stands in for
the pool. The hybrid-search primitive is either patched (to assert the call contract) or run
for real over the scripted rows (the end-to-end path) — see each test.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import build_graph
from app.agents.rag_agent import (
    DEFAULT_TOP_K,
    _allowed_document_ids,
    _parse_user_uuid,
    make_rag_node,
    retrieve,
)
from app.agents.state import AgentState, Intent, PlannerDecision, WorkerName
from tests.fakes import (
    FakeDBProvider,
    FakeEmbeddingClient,
    FakeExecuteResult,
    FakeSession,
    kb_title_row,
    make_search_result,
    rag_db_one_hit,
)

#: Where ``hybrid_search`` looks up the DB primitive — patch it here to assert the contract.
_HSC = "app.repositories.vector_search.hybrid_search_chunks"


class _RecordingSearch:
    """A ``hybrid_search_chunks`` double: records each call's args, returns canned results."""

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.calls: list[SimpleNamespace] = []

    async def __call__(
        self,
        session: Any,
        *,
        query_embedding: Any,
        query_text: str,
        k: int,
        vector_weight: float = 0.5,
        text_weight: float = 0.5,
        rrf_k: int = 60,
        kb_document_ids: Any = None,
    ) -> list[Any]:
        self.calls.append(
            SimpleNamespace(
                query_embedding=list(query_embedding),
                query_text=query_text,
                k=k,
                kb_document_ids=(list(kb_document_ids) if kb_document_ids is not None else None),
            )
        )
        return list(self._results)


def _state(message: str = "how do I grow?", **kw: Any) -> AgentState:
    return AgentState(session_id="s", user_message=message, **kw)


# --------------------------------------------------------------------------- #
# Embedding + search contract
# --------------------------------------------------------------------------- #
async def test_retrieve_embeds_query_and_searches_scoped_docs(monkeypatch: Any) -> None:
    doc_id = uuid4()
    embedder = FakeEmbeddingClient(vector=[0.5, 0.25, 0.125])
    search = _RecordingSearch([make_search_result(doc_id=doc_id, content="c")])
    monkeypatch.setattr(_HSC, search)
    session = FakeSession(
        [
            FakeExecuteResult([doc_id]),  # allowed document ids
            FakeExecuteResult([kb_title_row(doc_id=doc_id, title="T")]),  # titles
        ]
    )

    await retrieve(_state("how do I grow?"), embedder=embedder, db=FakeDBProvider(session))

    # the turn was embedded as a *query* (records go through embed_query).
    assert embedder.queries == ["how do I grow?"]
    # hybrid search was called once with the embedding, the text, k and the scoped ids.
    assert len(search.calls) == 1
    call = search.calls[0]
    assert call.query_embedding == [0.5, 0.25, 0.125]
    assert call.query_text == "how do I grow?"
    assert call.k == DEFAULT_TOP_K
    assert call.kb_document_ids == [doc_id]


# --------------------------------------------------------------------------- #
# Citation mapping + content bundle
# --------------------------------------------------------------------------- #
async def test_citations_and_content_map_from_search_results(monkeypatch: Any) -> None:
    doc_id, chunk_id = uuid4(), uuid4()
    search = _RecordingSearch(
        [
            make_search_result(
                chunk_id=chunk_id, doc_id=doc_id, content="A long excerpt about careers"
            )
        ]
    )
    monkeypatch.setattr(_HSC, search)
    session = FakeSession(
        [
            FakeExecuteResult([doc_id]),
            FakeExecuteResult([kb_title_row(doc_id=doc_id, title="Career Guide")]),
        ]
    )

    result = await retrieve(_state(), embedder=FakeEmbeddingClient(), db=FakeDBProvider(session))

    assert result.worker is WorkerName.RAG
    assert result.error is None
    assert result.data["chunk_count"] == 1
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.source_id == str(chunk_id)
    assert citation.title == "Career Guide"
    assert citation.snippet == "A long excerpt about careers"
    assert citation.worker is WorkerName.RAG
    # content bundles the numbered excerpt (grounding material, not a composed answer).
    assert result.content is not None
    assert result.content.startswith("[1] Career Guide:")
    assert "A long excerpt about careers" in result.content


async def test_long_snippets_are_truncated(monkeypatch: Any) -> None:
    doc_id = uuid4()
    long_text = "x" * 1000
    search = _RecordingSearch([make_search_result(doc_id=doc_id, content=long_text)])
    monkeypatch.setattr(_HSC, search)
    session = FakeSession(
        [
            FakeExecuteResult([doc_id]),
            FakeExecuteResult([kb_title_row(doc_id=doc_id, title="T")]),
        ]
    )

    result = await retrieve(_state(), embedder=FakeEmbeddingClient(), db=FakeDBProvider(session))

    snippet = result.citations[0].snippet
    assert snippet is not None
    assert snippet.endswith("…")
    assert len(snippet) <= 401  # SNIPPET_MAX_CHARS (+ the ellipsis)


# --------------------------------------------------------------------------- #
# Empty results / nothing in scope
# --------------------------------------------------------------------------- #
async def test_empty_results_yield_no_citations(monkeypatch: Any) -> None:
    search = _RecordingSearch([])  # nothing matched
    monkeypatch.setattr(_HSC, search)
    session = FakeSession([FakeExecuteResult([uuid4()])])  # only the allowed-ids read

    result = await retrieve(_state(), embedder=FakeEmbeddingClient(), db=FakeDBProvider(session))

    assert result.citations == []
    assert result.content is None
    assert result.error is None
    assert len(search.calls) == 1  # it did search, just found nothing


async def test_no_documents_in_scope_skips_search(monkeypatch: Any) -> None:
    search = _RecordingSearch([make_search_result()])
    monkeypatch.setattr(_HSC, search)
    session = FakeSession([FakeExecuteResult([])])  # empty allow-list

    embedder = FakeEmbeddingClient()
    result = await retrieve(_state(), embedder=embedder, db=FakeDBProvider(session))

    assert result.citations == []
    assert result.content is None
    # never embedded / searched when there is nothing in scope to search.
    assert embedder.queries == []
    assert search.calls == []


async def test_blank_query_returns_empty() -> None:
    result = await retrieve(
        _state("   "), embedder=FakeEmbeddingClient(), db=FakeDBProvider(FakeSession([]))
    )

    assert result.citations == []
    assert result.content is None
    assert result.error is None


# --------------------------------------------------------------------------- #
# Fail-soft on DB / embedding error
# --------------------------------------------------------------------------- #
async def test_retrieval_error_fails_soft() -> None:
    class BoomSession:
        async def execute(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("db down")

    result = await retrieve(
        _state(), embedder=FakeEmbeddingClient(), db=FakeDBProvider(BoomSession())
    )

    assert result.worker is WorkerName.RAG
    assert result.error is not None
    assert "db down" in result.error
    assert result.citations == []
    assert result.content is None


# --------------------------------------------------------------------------- #
# Access scoping (guest vs. logged-in user)
# --------------------------------------------------------------------------- #
async def test_guest_scope_is_shared_kb_only() -> None:
    session = FakeSession([FakeExecuteResult([])])

    await _allowed_document_ids(cast(AsyncSession, session), None)

    sql = str(session.statements[0])
    assert "IS NULL" in sql  # shared curated KB (user_id IS NULL)
    assert "OR" not in sql  # and nothing else — no private-doc predicate


async def test_logged_in_user_scope_includes_own_docs() -> None:
    session = FakeSession([FakeExecuteResult([])])

    await _allowed_document_ids(cast(AsyncSession, session), str(uuid4()))

    sql = str(session.statements[0])
    assert "IS NULL" in sql  # still includes the shared KB …
    assert "OR" in sql  # … plus the user's own documents.


def test_parse_user_uuid_variants() -> None:
    assert _parse_user_uuid(None) is None
    assert _parse_user_uuid("") is None
    assert _parse_user_uuid("not-a-uuid") is None
    valid = uuid4()
    assert _parse_user_uuid(str(valid)) == valid


# --------------------------------------------------------------------------- #
# Node adapter (make_rag_node → graph update shape)
# --------------------------------------------------------------------------- #
async def test_node_without_db_fails_soft() -> None:
    node = make_rag_node()  # no provider bound (the import-time default posture)

    update = await node(_state())

    assert set(update) == {"worker_results", "citations"}
    result = update["worker_results"][WorkerName.RAG.value]
    assert result.error is not None
    assert update["citations"] == []


async def test_node_wraps_result_into_partial_update(monkeypatch: Any) -> None:
    doc_id = uuid4()
    search = _RecordingSearch([make_search_result(doc_id=doc_id, content="x")])
    monkeypatch.setattr(_HSC, search)
    session = FakeSession(
        [
            FakeExecuteResult([doc_id]),
            FakeExecuteResult([kb_title_row(doc_id=doc_id, title="T")]),
        ]
    )
    node = make_rag_node(embedder=FakeEmbeddingClient(), db=FakeDBProvider(session))

    update = await node(_state())

    assert set(update) == {"worker_results", "citations"}
    assert WorkerName.RAG.value in update["worker_results"]
    assert len(update["citations"]) == 1


# --------------------------------------------------------------------------- #
# End-to-end through the real compiled graph
# --------------------------------------------------------------------------- #
def _planner_selecting_rag() -> Any:
    def planner(state: AgentState) -> dict[str, Any]:
        return {"plan": PlannerDecision(intent=Intent.CV_QUESTION, workers=[WorkerName.RAG])}

    return planner


async def test_rag_routed_turn_populates_state_end_to_end() -> None:
    """A RAG-routed turn through the real graph yields populated citations + worker result."""
    db, _doc_id, chunk_id = rag_db_one_hit(
        title="Career KB", content="Networking tips for switching fields"
    )
    compiled = build_graph(
        planner=_planner_selecting_rag(),
        embedder=FakeEmbeddingClient(),
        db=db,
    )

    result = AgentState.model_validate(await compiled.ainvoke(_state("how do I switch careers?")))

    assert WorkerName.RAG.value in result.worker_results
    rag = result.worker_results[WorkerName.RAG.value]
    assert rag.error is None
    assert rag.content is not None
    assert "Career KB" in rag.content
    # citations accumulated on the state via the P4-01 reducer.
    assert len(result.citations) == 1
    assert result.citations[0].source_id == str(chunk_id)
    assert result.citations[0].worker is WorkerName.RAG


def test_e2e_uses_a_valid_uuid_chunk_id() -> None:
    """Guard: the scripted chunk id is a real UUID (source_id round-trips)."""
    _db, _doc_id, chunk_id = rag_db_one_hit()
    assert uuid.UUID(str(chunk_id))
