# Engineer report — P4-04-rag-agent · Revision 1

## Summary
Replaced the P4-02 `rag_node` stub with a real retrieval worker in a new
`backend/app/agents/rag_agent.py`. The worker embeds the current turn, hybrid-searches the
pgvector KB (shared curated content + the caller's own private CV docs), and returns a
`WorkerResult` with grounded excerpts + one `Citation` per chunk. It performs **retrieval +
citation only** — no LLM synthesis (that stays the responder's job, P4-05/06). `graph.py`'s
`rag_node` now delegates to this implementation via a `make_rag_node(embedder=, db=)`
closure; topology/edges/reducers are unchanged. Retrieval fails soft (a `WorkerResult.error`,
never an exception out of the node), and access scoping guarantees guests never reach another
user's private documents.

## Files changed
- `backend/app/agents/rag_agent.py` (new) — the RAG worker: `retrieve()` (pure logic →
  `WorkerResult`), `make_rag_node()` (LangGraph node adapter binding collaborators), a
  `SessionProvider` Protocol seam, access-scoping (`_allowed_document_ids` /
  `_parse_user_uuid`), citation mapping and excerpt bundling.
- `backend/app/agents/graph.py` — import `make_rag_node`/`SessionProvider`; module-default
  `rag_node = make_rag_node()`; `build_graph` gains `embedder=`/`db=` seams and wires a
  provider-bound RAG node when given; docstring stub-marker updated. Topology unchanged.
- `backend/app/agents/__init__.py` — export `make_rag_node`, `retrieve`.
- `backend/tests/fakes.py` — shared RAG test doubles (`FakeEmbeddingClient`, scripted
  `FakeSession`/`FakeDBProvider`, `SearchResult`/row builders, `rag_db_one_hit`).
- `backend/tests/test_rag_agent.py` (new) — unit + end-to-end coverage (see Tests).
- `backend/tests/test_agent_graph.py` — the P4-02 graph tests that route through RAG now run
  via the **async** runtime (`astream`/`ainvoke`) because `rag_node` is now an async node;
  the two fan-in tests inject fake embedder + scripted DB so RAG contributes like any worker.

## Key decisions
- **Reuse the P2-06 primitive, resolve scope as a document-id allow-list (design §3/§4).**
  `hybrid_search`/`hybrid_search_chunks` filter by `kb_document_ids`, not `user_id`, so the
  worker resolves the allowed set up front with one small `SELECT` on `kb_documents`
  (`user_id IS NULL` for guests; `+ user_id = state.user_id` for a logged-in user) and passes
  it through. An explicit list is **always** passed (never `None`, which would mean "no
  filter" and leak every user's private docs); an empty allow-list simply yields nothing. The
  curated KB is a bounded corpus, so materialising ids is cheap — noted follow-up if it grows:
  push the ownership predicate into the search query (a repository change), out of scope here.
- **Retrieval-only, no generation (design §3).** `content` is a numbered bundle of top-k
  excerpts (grounding material for the responder), not a composed answer. The worker never
  calls the LLM.
- **Fail-soft mirrors the planner (P4-03).** Any embedding/DB error → `WorkerResult(error=…)`
  with empty citations; the node never raises, so a broken KB can't 500 the turn.
- **DI via a `SessionProvider` Protocol (mirrors P4-03's `LLMCompleter`).** `retrieve` depends
  on a capability, not the concrete `PostgresConnectionProvider`; production wires the shared
  pool, tests inject a scripted fake. Uses the provider's `session()` context manager (works
  outside a FastAPI request, unlike `get_db_session`).
- **No rogue second pool.** The module-default `rag_node` binds **no** DB provider — it fails
  soft if routed without one. The shared pool is injected via `build_graph(db=…)` when the
  chat endpoint wires the graph (a later task), honoring the design §4 single-shared-pool rule
  rather than creating a second `from_settings()` pool at graph import. The embedder default is
  the settings-configured in-process `SentenceTransformerEmbeddingClient` (lazy — no model
  load).
- **Async node ripple (expected).** A real DB/embedding node must be `async`, so any turn that
  routes through RAG is driven via LangGraph's async runtime. The P4-02 graph tests that route
  RAG were converted from sync `invoke`/`stream` to `ainvoke`/`astream` — a root-cause
  consequence of the node becoming real, not a topology change (production already runs the
  graph via `run_graph` → `ainvoke`).

## How to verify
- `cd backend`
- `.venv/bin/python -m ruff check app/agents tests/test_rag_agent.py tests/test_agent_graph.py tests/fakes.py`
- `.venv/bin/python -m mypy app/` (CI scope: `app/` + `migrations/`)
- `.venv/bin/python -m pytest tests/test_rag_agent.py tests/test_agent_graph.py tests/test_agent_planner.py -q`
- Full suite: `.venv/bin/python -m pytest -q`

## Tests (final step — mandatory)
- `ruff check` (my files) → **All checks passed!**
- `ruff format --check` (my files) → **6 files already formatted.**
- `mypy app/` → **Success: no issues found in 66 source files.**
- `pytest` (full suite) → **260 passed, 43 skipped** (skips are the live-DB-gated P2-09
  integration tests — no DB in the sandbox, exactly as before).
- New `tests/test_rag_agent.py` (15 tests) covers: query embedded + `hybrid_search` invoked
  with the query vector / text / `k` / scoped `kb_document_ids`; citation + content mapping;
  snippet truncation; empty-results and nothing-in-scope; fail-soft on DB error; guest vs.
  logged-in scoping; `_parse_user_uuid`; the node adapter shape; and an **end-to-end** run
  through the real compiled `build_graph` proving a RAG-routed turn populates
  `worker_results['rag']` + `AgentState.citations`.
- No failures required a fix. The P4-02 graph tests were updated (sync→async) as the
  root-cause consequence of `rag_node` becoming an async node — the tests assert the same
  behavior, just via the async runtime the real node requires.

### Note on unrelated files
`ruff format --check .` (whole-tree) also flags 4 files I did **not** touch
(`app/repositories/models/identity.py`, `tests/test_agent_planner.py` [untracked, from
P4-03], `tests/test_feedback_reader.py`, `tests/test_p3_exit_verification.py`). This is
pre-existing ruff-version drift, not introduced by this task; I left them alone to avoid
churn in other tasks' files. Two pre-existing `mypy` errors on `tests/` are likewise
unrelated and outside CI's `mypy app/ migrations/` scope.

## Self-check
- [x] Meets acceptance criteria (real retrieval; graph wired; scope enforced; fails soft;
      unit + real-graph e2e tests; ruff/mypy clean; existing suite green).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (worker uses the
      repository primitive + `EmbeddingClient` interface; no driver access in the agent).
- [x] Tests/lints pass (pasted above).
- [x] Graph topology/edges/reducers unchanged; `[STUB → P4-04]` marker removed.
- [x] Out-of-scope untouched: web/job/PDP stubs, responder synthesis, `AgentState`/reducers,
      the `POST /api/chat` wiring.
