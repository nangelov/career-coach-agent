# Task P4-04-rag-agent — RAG worker (embed, retrieve, cite)

- **Phase:** P4   **Status:** ENG   **Tags:** (B)

## Scope

From `dev-board/tasks.md` P4:
> **(B)** `agents/rag_agent.py` — embed query, retrieve from pgvector, return grounded snippets + citations.

Replace the **stub** `rag_node` body in `backend/app/agents/graph.py` (see its `[STUB → P4-04]` docstring)
with a real implementation in a new `backend/app/agents/rag_agent.py`, and wire `graph.py` to call it. Do not
change the graph's topology/edges/conditional-routing/reducers — only swap what `rag_node` does. Keep the node
function's identity/name (`rag_node`) per the P4-02 contract; the `[STUB → P4-04]` marker should be
removed/updated once real.

The RAG worker (design §3): embeds the current turn's query, retrieves from the pgvector knowledge base
(curated career/learning content + the user's parsed CV chunks — both already modeled as `kb_documents` /
`kb_chunks` in P2-04), and returns grounded snippets with citations for the responder to synthesize/cite.

## What already exists — reuse, don't reinvent

- `backend/app/llm/embeddings.py` (P2-06) — `EmbeddingClient` interface (`embed_query` applies the Qwen3
  query instruction) + `SentenceTransformerEmbeddingClient`. Inject an `EmbeddingClient`, don't construct a
  new embedding path.
- `backend/app/repositories/vector_search.py` (P2-06/P2-09) — `hybrid_search` (embed-then-search convenience)
  and `hybrid_search_chunks` (weighted RRF fusion of cosine + `ts_rank` over `kb_chunks`, with
  `vector_weight`/`text_weight`/`rrf_k`/`kb_document_ids` knobs) plus `SearchResult` (chunk_id,
  kb_document_id, content, score, vector_similarity, text_rank, meta). This is the retrieval primitive — call
  it, do not hand-roll a new pgvector query.
- `backend/app/repositories/postgres.py` — `PostgresConnectionProvider.session()` async context manager
  (works outside a FastAPI request, unlike the `get_db_session` dependency, which needs a `Request`) for
  acquiring an `AsyncSession` from the shared pool inside a graph node.
- `backend/app/agents/state.py` (P4-01) — `WorkerResult` (per-worker content/citations/data/error) and
  `Citation` (source_id/title/url/snippet/worker) — the shapes this worker must fill.
- `backend/app/agents/planner.py` (P4-03) — the pattern for injecting a collaborator into a graph node via a
  `build_graph(...)` constructor seam (there it was `router: LLMCompleter`); follow the same shape for
  injecting the embedder + DB session provider into `rag_node` (e.g. `build_graph(embedder=..., db=...)`),
  keeping production defaults wired from `app.config.settings` / the app-level singletons and tests able to
  inject fakes.

## Implementation approach

- `agents/rag_agent.py` exposes a function (e.g. `async def retrieve(state: AgentState, *, embedder:
  EmbeddingClient, db: PostgresConnectionProvider) -> WorkerResult`) that:
  1. Builds a query string from `state.user_message` (and optionally recent `state.history` context — keep
     it simple, the query itself is usually sufficient).
  2. Calls `hybrid_search` (or `hybrid_search_chunks` if you already have an embedding) to retrieve top-k
     `kb_chunks`, restricted appropriately: shared curated KB (`kb_documents.user_id IS NULL`) plus, when
     `state.user_id` is set, that user's own private CV-derived documents. `hybrid_search_chunks` takes a
     `kb_document_ids` filter, not a `user_id` filter directly — resolve the allowed document id set first (a
     small query against `kb_documents`) or extend the call site accordingly; document whatever approach you
     take.
  3. Maps each `SearchResult` into a `Citation` (`source_id=str(chunk_id)`, `title` from the parent
     `kb_documents.title` — a join or small follow-up lookup is fine, `snippet` from `content` (truncate
     sensibly), `worker=WorkerName.RAG`) and synthesizes `WorkerResult.content` as a grounded snippet bundle
     (e.g. concatenated top-k excerpts) — do not have this worker call the LLM to "answer" the question; that
     synthesis is the **responder's** job (P4-05/06). This worker's job is retrieval + citation, not
     generation.
  4. Fails soft on any DB/embedding error (`WorkerResult(worker=RAG, error=...)`, empty citations) — a
     retrieval failure must not crash the turn; the responder can still answer from other workers or a plain
     answer.
- Wire `graph.py`'s `rag_node` to call this, injecting the app's `EmbeddingClient` and
  `PostgresConnectionProvider` (module-level singletons/config, mirroring how `router` is threaded into
  `planner.py`/`build_graph`).
- No live embedding model or live Postgres in unit tests — inject fakes (a fake `EmbeddingClient` returning a
  fixed vector; a fake/mock session or a lightweight in-memory stand-in for `hybrid_search_chunks`'s DB call).
  If an integration-style test against a real pgvector container is valuable, gate it exactly like the
  existing P2-09 live-DB-gated integration tests (skip when `DATABASE_URL`/container unavailable) — don't
  make it required for the default `pytest` run.

## Acceptance criteria

- [ ] `backend/app/agents/rag_agent.py` implements real retrieval using `EmbeddingClient` +
      `hybrid_search`/`hybrid_search_chunks`, producing a `WorkerResult` with grounded `content` and populated
      `citations`.
- [ ] `graph.py`'s `rag_node` calls this real implementation; graph topology/edges/reducers unchanged; the
      `[STUB → P4-04]` docstring marker is updated/removed.
- [ ] Retrieval scope: shared curated KB always in scope; user's own CV-derived documents included only when
      `state.user_id` is set (guests never see another user's private docs — reuse the existing
      user-scoping posture from P2/P3, don't invent a new access rule).
- [ ] Fails soft: embedding/DB errors produce a `WorkerResult.error`, not an unhandled exception out of the
      node (mirrors the planner's `LLMError`-caught / safe-default pattern from P4-03).
- [ ] Unit tests: query embedding + hybrid search invoked with expected args (mocked collaborators), citations
      correctly mapped from `SearchResult`, empty-results case handled, error path fails soft, and an
      integration-style test running the **real compiled graph** (`build_graph`) with fakes proves a `RAG`-
      routed turn ends up with `AgentState.citations`/`worker_results["rag"]` populated end-to-end.
- [ ] `ruff` + `mypy` clean; existing backend test suite (P4-01..P4-03 tests included) still green.

## Design references

- `dev-board/app-design-and-features.md` §3 — RAG Agent bullet (line ~128).
- `dev-board/app-design-and-features.md` §4 — `kb_documents`/`kb_chunks` ownership (shared vs private CV docs).
- `dev-board/code-review/P2-06-embeddings/`, `P2-09-integration-verify/` — `EmbeddingClient` +
  `hybrid_search` background and the live-DB-gated test pattern to follow if you add one.
- `dev-board/code-review/P4-01-agent-state/`, `P4-02-agent-graph/`, `P4-03-planner/` — the state/graph/planner
  this worker plugs into.

## Constraints / non-goals

- Do NOT implement web search, job search, or PDP/resume workers (later P4 tasks) — leave their stubs as-is.
- Do NOT implement the responder's synthesis (P4-05/06) — this worker returns grounded material, it does not
  compose the final answer.
- Do NOT change `AgentState`, the graph topology, or the P4-01 reducers.
- Do NOT wire this into the P1 `POST /api/chat` endpoint yet.
- Do NOT require a live Postgres/embedding model for the default test run.
