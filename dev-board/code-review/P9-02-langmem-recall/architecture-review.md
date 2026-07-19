# Architecture review — P9-02-langmem-recall · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 target structure | teachable memory lives under `app/memory/` (§8 tree line "memory/") | New `app/memory/store.py` + `__init__.py`; recall worker in `app/agents/memory_agent.py` | Conforms. |
| A2 | §5.4 recall step | pre-turn, in-graph: fetch explicit prefs + top-k `user_memories` → context, before planner | `recall()` reads `preferences.data` JSONB + top-k cosine `user_memories` into `MemoryContext`; node sits at `MEMORY_RECALL` between input-guardrail and planner (unchanged topology) | Conforms. |
| A3 | §6.7 LangMem + pgvector-backed store | memory vectors stay in pgvector `user_memories`; LangMem drives a pgvector-backed store, no parallel schema | `UserMemoryStore(BaseStore)` adapts the existing `user_memories` schema, namespaced `("memories","<user_id>")`; `abatch` services `SearchOp` so LangMem tooling *can* drive it; no LangGraph Postgres store spun up | Conforms. See Note 1 (recall bypasses LangMem tooling — accepted). |
| A4 | Interfaces-before-impl | reuse the repo vector primitive, don't hand-roll pgvector | Store calls P2-06 `search_user_memories`; embedder + `SessionProvider` injected by keyword (no self-constructed pool/embedder) | Conforms — matches the blessed RAG seam. |
| A5 | §4 data ownership / guests | guests durable-store-free; user-scoped access | Guest / non-UUID `user_id` → default-empty `MemoryContext`, never touches DB; P9-07 guest session personalization correctly deferred | Conforms. |
| A6 | DI convention (§3, prior P4/P6 rulings) | wire via existing `embedder=`/`db=` like RAG/market; bootstrap injects singletons | `build_graph` resolves the bound node when `db` given; `GraphTurnStreamer`/`stream_graph` thread it through; `bootstrap.py` already passes `db=pg_provider` + shared embedder — no wiring change needed | Conforms. `db`-only gate is correct (prefs read needs the pool). |
| A7 | State contract (P4-01) | `memory: MemoryContext` is single-writer (no reducer) | Node returns `{"memory": ctx}`; `AgentState.memory` has no `Annotated` reducer | Conforms — sole writer, matches the agent-state ruling. |
| A8 | Fail-soft posture | any DB/embedding error → empty context, never crash the turn (RAG/market parity) | Store propagates; node wraps whole read in try/except → `MemoryContext()` + warn log | Conforms. |
| A9 | Locked stack / budget | Postgres+pgvector+JSONB only; in-process sentence-transformers; free/OSS | Uses `user_memories` vector + `preferences` JSONB; reuses shared `SentenceTransformerEmbeddingClient`; no new paid/managed dependency | Conforms. |
| A10 | Phase fit | P9-02 recall only; no learn/CRUD/responder-adaptation coupling | Write ops (`PutOp`/get/list) raise `NotImplementedError` with explicit P9-03/P9-05 boundary; responder consumption deferred to P9-06 | Conforms. |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (store = repo-facing infra; node = agent layer; service untouched)
- [x] Honors locked decisions (LangMem over pgvector `user_memories`, no parallel schema; Postgres+Redis only; in-process embeddings; no ReAct)
- [x] Interfaces-before-implementations (`BaseStore` adapter as the shared seam; reuses `search_user_memories`; injected embedder/`SessionProvider`)
- [x] Budget posture respected (free/OSS/self-hosted)

## Notes
1. **Recall calls `search_memories` directly, not through LangMem's `create_memory_store_manager`.** The task said recall should be "backed by LangMem"; the engineer instead built a `BaseStore`-conforming adapter (the LangMem-compatible *seam*) and drives search first-party. This is a defensible reading — acceptance only requires a "LangMem-compatible adapter … exposing at least similarity search," §6.7's contract is that the *vectors* live in pgvector under a LangMem-drivable store, and it avoids pulling LangMem's manager into the hot request path for a plain top-k. `abatch(SearchOp)` keeps the door open for LangMem to drive the same query in P9-03. Accepted, not a blocker; logged so P9-03 consciously decides whether the learn step goes through `create_memory_store_manager` or stays first-party.
2. **`UserMemoryStore` is the single home for `user_memories` vector access.** P9-03 (learn: put/update/delete) and P9-05 (CRUD API) must extend *this* store rather than open a second path — the `NotImplementedError` boundaries mark exactly where. Good foundation-first shape.
3. Namespace helper accepts a 1-tuple candidate as a fallback — harmless robustness, no design concern.
