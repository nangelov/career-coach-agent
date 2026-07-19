---
name: pattern-memory-recall-store
description: P9-02 blessed — UserMemoryStore BaseStore adapter over pgvector user_memories (single home); recall-only, first-party search allowed over LangMem manager; guests durable-free
metadata:
  type: project
---

P9-02 (langmem-recall) APPROVED rev 1. Blessed the teachable-memory recall seam.

**Ruling / blessed pattern:**
- `app/memory/store.py::UserMemoryStore(langgraph.store.base.BaseStore)` is the **single home** for
  vector access to `user_memories`, namespaced `("memories","<user_id>")`, over the P2-04 schema —
  **no parallel LangGraph Postgres store** (§6.7). P9-03 (learn put/update/delete) and P9-05 (CRUD API)
  MUST extend this store, not open a second path; the `NotImplementedError` on Put/Get/list ops marks
  exactly where. Reuses P2-06 `search_user_memories` primitive (no hand-rolled pgvector).
- Recall worker `app/agents/memory_agent.py::recall` sits at `MEMORY_RECALL` (input-guardrail→planner),
  writes `{"memory": MemoryContext}` — single-writer, **no reducer** (matches [[project-agent-state]]).
  Reads `preferences.data` JSONB + top-k cosine memories. Fail-soft to empty `MemoryContext` (RAG/market
  parity). Guests / non-UUID user_id → empty context, never touch DB (guest personalization = P9-07).
- Wired via existing `embedder=`/`db=` DI (no `memory_provider=` kwarg); `db is not None` gate is correct
  (prefs read needs the pool). bootstrap already injects both into GraphTurnStreamer — no wiring change.

**Why:** §5.4 point 1 (pre-turn recall), §6.7 (LangMem over pgvector-backed store), §4 (guests durable-free).

**How to apply:** For P9-03/05, verify they extend UserMemoryStore rather than duplicate vector access.
**Accepted deviation (logged):** recall calls `search_memories` directly, NOT LangMem's
`create_memory_store_manager`. Defensible — the BaseStore adapter IS the LangMem-compatible seam and
`abatch(SearchOp)` keeps LangMem drivable; §6.7's contract is about where vectors live, not forcing the
manager into the request path. P9-03 should consciously decide manager-vs-first-party for the learn step.
Related: [[project-agent-graph]], [[project-hybrid-search]], [[project-v2-locked-stack]].
