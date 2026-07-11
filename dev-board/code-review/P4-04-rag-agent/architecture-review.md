# Architecture review — P4-04-rag-agent · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | RAG worker lives in `agents/`; retrieval SQL in `repositories/` | New `app/agents/rag_agent.py`; all pgvector access delegated to the P2-06 `hybrid_search` repo primitive — no hand-rolled query in the agent | none |
| A2 | §8 layering | Agent → Repository/LLM interface; agent never touches the DB driver | Worker depends on `EmbeddingClient` interface + `hybrid_search`; DB access via `SessionProvider` Protocol / `session()` ctx-mgr, no driver calls | none |
| A3 | §3 RAG role | Embed query, retrieve grounded snippets + citations; **no** answer synthesis | `retrieve()` returns bundled top-k excerpts + one `Citation` per chunk; never calls the LLM (synthesis left to responder P4-05/06) | none |
| A4 | §4 data ownership | Shared curated KB (`user_id IS NULL`) always; user's private CV docs only when logged in; guests never see others' private docs | `_allowed_document_ids` scopes to `user_id IS NULL` + (`user_id == state.user_id` when set); always passes an explicit id allow-list (never `None`) so no leak | none |
| A5 | locked: in-process embeddings | `sentence-transformers` `EmbeddingClient`, no API path | Injects `EmbeddingClient`; default is settings-configured `SentenceTransformerEmbeddingClient` (lazy, no eager load); no new embedding path | none |
| A6 | locked: Postgres+Redis only | pgvector KB, no MongoDB, single shared pool (§4) | pgvector via existing primitive; module-default RAG node binds **no** DB → fails soft rather than opening a second `from_settings()` pool; shared pool injected via `build_graph(db=...)` later | none |
| A7 | graph contract (P4-02) | Swap `rag_node` body only; topology/edges/reducers/`WorkerName.RAG` identity unchanged | `make_rag_node()` closure keeps the `rag` node name; `_node_update` writes `worker_results[rag]` + list-concat `citations` via P4-01 reducers; edges/fan-out/fan-in untouched; `[STUB → P4-04]` marker updated | none |
| A8 | DI seam consistency (P4-03) | Inject collaborator via `build_graph(...)` Protocol, mirroring `LLMCompleter` | `SessionProvider` Protocol + `embedder=`/`db=` seam on `build_graph`; production singletons vs. test fakes — structurally matches the planner pattern | none |
| A9 | fail-soft posture (P4-03) | Retrieval error → safe `WorkerResult`, never raises out of the node | DB/embedding error caught → `WorkerResult(error=...)`, empty citations; empty-query and nothing-in-scope short-circuit cleanly | none |
| A10 | phase fit | P4 worker; not wired into P1 `POST /api/chat`; other workers left as stubs | Only `rag_node` made real; web/job/PDP/responder stubs untouched; no chat-endpoint wiring | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Agent → Repository/LLM interface; no driver leak into the agent)
- [x] Honors locked decisions (in-process embeddings; Postgres+pgvector only, no Mongo; single shared pool; no ReAct parser reintroduced)
- [x] Interfaces-before-implementations (`EmbeddingClient` + `SessionProvider` Protocol seams; reuses the `hybrid_search` repository primitive rather than duplicating it)
- [x] Budget posture respected (free/OSS/self-hosted in-process embeddings; no paid retrieval path)

## Notes
- **Scaling follow-up (not a blocker):** `_allowed_document_ids` materialises the full shared-KB
  document-id set on every turn and passes it as an `IN (...)` allow-list. Correct and cheap for the
  current bounded curated corpus; the engineer documented the intended evolution (push the ownership
  predicate into the search query — a `repositories/` change) if the KB grows large. Logged as a
  design follow-up, appropriate to defer since it is a localized repository change over the same
  result contract.
- **Broad `except Exception` in `retrieve`** is a deliberate fail-soft choice for a node that must never
  crash the turn (task explicitly asks for "any DB/embedding error"). Acceptable at the design level;
  whether to narrow it to the DB/embedding error taxonomy is a code-reviewer call, not a conformance gap.
- **Async-node ripple** (P4-02 graph tests moved sync→async) is a correct consequence of the node
  becoming a real I/O node — production already drives the graph via `run_graph → ainvoke`. No topology
  change; the fan-out/fan-in contract is preserved.
- Planner classify/route split (my prior ruling) remains honored: this worker is dispatched by the
  deterministic `_INTENT_WORKERS` routing; it does not introduce any model-emitted worker/node names.
