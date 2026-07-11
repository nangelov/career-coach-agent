---
name: pattern-worker-node-di-scope
description: Blessed P4 worker-node shape — Protocol DI seam, no rogue pool, access-scoped allow-list, retrieval-only
metadata:
  type: project
---

The P4-04 RAG worker (`app/agents/rag_agent.py`) set the template every real P4 worker
(web/job/PDP, P4-05/06) should follow:

- **DI via a structural `Protocol`, not a concrete class.** `SessionProvider` (satisfied by
  `PostgresConnectionProvider`) mirrors the planner's `LLMCompleter` seam. `build_graph(embedder=,
  db=)` binds production singletons; tests inject fakes. Worker never constructs an embedding path
  or a DB pool itself. See [[pattern-planner-classify-route-split]].
- **No rogue second pool (§4 single-shared-pool).** The module-default node binds **no** DB
  provider and **fails soft if routed** — the shared pool is injected only when the chat endpoint
  wires the graph. Do NOT accept a worker calling `from_settings()` / opening its own pool at
  graph import.
- **Access scoping = explicit allow-list, never `None`.** Retrieval that filters by document/id
  must always pass an explicit id list (shared `user_id IS NULL` always; private `user_id ==
  state.user_id` only when set). Passing `None`/omitting the filter = leak. Guests see shared-only.
- **Retrieval-only, no LLM generation.** Workers return grounded material + `Citation`s; synthesis
  is the responder's job (P4-05/06). Reject a worker that calls the LLM to "answer".
- **Fail-soft, node never raises.** Any DB/embedding error → `WorkerResult(error=...)`, empty
  citations. Graph topology/edges/reducers stay untouched — swap the node *body* only. A real I/O
  node becoming `async` (rippling sync graph tests → `ainvoke`/`astream`) is expected, not a
  topology change.
