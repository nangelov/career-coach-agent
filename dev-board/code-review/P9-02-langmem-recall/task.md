# Task P9-02-langmem-recall — LangMem recall wired before the planner
- **Phase:** P9   **Status:** ENG   **Tags:** (B)

## Scope
Replace the `memory_recall_node` stub in `backend/app/agents/graph.py` with a **real** recall
step, backed by **LangMem** (already a dependency, `langmem>=0.0.1`), that runs before the
planner and populates `AgentState.memory` (`MemoryContext.preferences` + `.memories`).

From `dev-board/tasks.md` (P9):
> `memory/` on **LangMem** (in-process, over pgvector `user_memories`) — recall step (explicit
> prefs + top-k `user_memories` → context) wired into the graph before the planner.

### What already exists (read before building)
- `backend/app/agents/graph.py` — `memory_recall_node` is a no-op stub; `MEMORY_RECALL` sits
  between `INPUT_GUARDRAIL` and `PLANNER` in the compiled graph already. `build_graph(...)`
  follows a consistent DI pattern for every worker (`embedder=`, `db=` optional kwargs that
  swap a bound closure in for the module-level default) — **follow that same pattern** for
  memory (e.g. `build_graph(memory_provider=...)` or reuse `embedder=`/`db=` if that's a clean
  fit — your call, but stay consistent with the existing convention).
- `backend/app/agents/state.py` — `MemoryContext(preferences: dict, memories: list[str])` is
  the target shape already on `AgentState.memory`.
- `backend/app/repositories/models/identity.py::Preference` — `preferences` table (one row per
  user, JSONB `data`), already migrated (P2).
- `backend/app/repositories/models/knowledge.py::UserMemory` — `user_memories` table (`text`,
  `embedding vector(4096)`, `memory_type`, `confidence`, `source_message_id`), already
  migrated (P2). **Schema-only today** — this task is the first to read/write it for real.
- `backend/app/agents/rag_agent.py` — the pattern to mirror for "embed the turn, hybrid/vector
  search a pgvector table, inject into state, fail soft on any error, DI via a `SessionProvider`
  protocol + `EmbeddingClient`". `backend/app/repositories/vector_search.py` has the existing
  cosine-search primitive you can reuse or adapt for `user_memories`.
- `backend/.venv/lib/python3.11/site-packages/langmem/` — LangMem's extraction/store tooling
  expects a LangGraph `BaseStore` (`langgraph.store.base.BaseStore`), e.g.
  `create_memory_store_manager(..., store=...)`. Our design (§6.7) says memory vectors "continue
  to live in our pgvector `user_memories` table where LangMem supports a pgvector-backed store"
  — so build a **thin `BaseStore`-conforming adapter** over the existing `UserMemory`
  repository/table (namespaced by `user_id`) rather than letting LangGraph's own Postgres store
  create/manage a parallel schema. This adapter is shared infrastructure: this task uses it for
  **search** (recall); P9-03 (learn step, separate task) will reuse it for **put/update/delete**.
  Keep the adapter itself in a clearly-named module (e.g. `app/memory/store.py`) since P9-03 and
  P9-05 (memory CRUD API) both depend on it.

## Acceptance criteria
- [ ] A `BaseStore`-conforming (or otherwise LangMem-compatible) adapter over `user_memories`,
      namespaced per user, exposing at least similarity search (top-k) — reusable by later P9
      tasks. Document the interface briefly (docstring) since P9-03/P9-05 build on it.
- [ ] `memory_recall_node` (or its replacement, wired the same way every other real worker is)
      does, for a **logged-in user** (`state.user_id` set):
      - fetches the user's explicit `preferences.data` JSONB → `MemoryContext.preferences`;
      - embeds `state.user_message` and fetches top-k (e.g. 5) `user_memories` by cosine
        similarity for that user → `MemoryContext.memories` (list of the memory text strings).
- [ ] For a **guest** (`state.user_id is None`): no durable recall — `MemoryContext` stays
      empty/default (guest session-only personalization is P9-07; do not build Redis wiring
      here, just don't break/crash for guests).
- [ ] Fails soft: any DB/embedding error yields empty `MemoryContext` (never crashes the turn) —
      same posture as the RAG/market workers.
- [ ] Wired into `build_graph`/`GraphTurnStreamer`/`stream_graph` via the same DI convention as
      the other workers (production singletons injected from the chat-endpoint composition root
      you find in `backend/app/api/chat.py` or equivalent wiring module — grep for where
      `db=`/`embedder=` are currently passed into `build_graph` and add memory alongside them).
- [ ] Unit tests: preferences + memories populate correctly for a user with data; empty defaults
      for a user with none; guests get empty `MemoryContext`; a simulated DB/embedding failure
      degrades to empty `MemoryContext` rather than raising.

## Design references
- dev-board/app-design-and-features.md: §5.4 (Personalization — the teachable agent), point 1
  "Recall (pre-turn, in graph)"; §6.7 (LangMem decision + pgvector-backed store rationale).
- dev-board/plan.md: P9.
- `backend/app/agents/graph.py` module docstring (graph shape, node replacement contract).

## Constraints / non-goals
- No learn/extraction step (Celery post-turn write-back) — that is P9-03.
- No PII redaction / GDPR Art. 9 exclusion filtering of what gets *written* — those gate the
  learn step (P9-04) and don't apply to reading existing rows here.
- No responder tone/depth adaptation logic — that is P9-06 (this task only makes the context
  available on `AgentState.memory`).
- No `GET/PUT/DELETE /api/memory` endpoints — that is P9-05.
- No frontend changes.
