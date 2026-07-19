# Engineer report — P9-02-langmem-recall · Revision 1

## Summary
Replaced the `memory_recall_node` no-op stub with a **real** pre-planner recall step (design
§5.4 / §3). For a logged-in user it populates `AgentState.memory` with the explicit
`preferences.data` JSONB + the top-k learned `user_memories` (cosine similarity to the turn).
Guests and any DB/embedding error degrade to an empty `MemoryContext` (fail-soft). Added the
reusable, `BaseStore`-conforming `UserMemoryStore` adapter over `user_memories` (namespaced per
user) that P9-03 (learn) and P9-05 (CRUD API) build on. Wired via the existing `embedder=`/`db=`
DI convention — no bootstrap change was needed (they were already passed into `GraphTurnStreamer`).

## Files changed
- `backend/app/memory/store.py` (new) — `UserMemoryStore(BaseStore)`: typed `search_memories`
  (embed → `search_user_memories` cosine top-k) + `abatch` servicing `SearchOp`; `batch` and the
  write ops (`PutOp`/`GetOp`/list) raise `NotImplementedError` (owned by P9-03/P9-05). Namespace
  helper `memory_namespace(user_id) → ("memories", "<user_id>")`.
- `backend/app/memory/__init__.py` — export the store + namespace/constants.
- `backend/app/agents/memory_agent.py` (new) — `recall(state, *, store, db, k)` (prefs +
  memories, fail-soft) and `make_memory_recall_node(...)` closure (RAG-pattern DI). Unbound
  default is **sync** so the no-db module graph stays synchronously invokable.
- `backend/app/agents/graph.py` — import + resolve the recall node from `db`/`embedder`; module
  default `memory_recall_node = make_memory_recall_node()`; updated node docstrings.
- `backend/app/agents/__init__.py` — export `make_memory_recall_node`, `recall`.
- `backend/tests/fakes.py` — reusable `user_memory_row(...)` helper (P9-03/P9-05 will reuse).
- `backend/tests/test_memory_agent.py` (new) — 16 unit + integration tests.

## Key decisions
- **Reused `embedder=`/`db=` rather than a new `memory_provider=` kwarg** (task allowed either).
  Recall needs exactly the shared embedder + Postgres pool the RAG/market workers already bind,
  so this keeps `build_graph`/`GraphTurnStreamer`/`stream_graph`/bootstrap wiring untouched and
  consistent (design §3, §5.4). The store is constructed inside the node from those.
- **`BaseStore` conformance is intentionally thin — search only** (acceptance says "exposing **at
  least** similarity search"). `abatch` services `SearchOp`; write ops raise loudly so the P9-03
  boundary is explicit, not silently wrong (§6.7 pgvector-backed store). No LangMem
  `create_memory_store_manager` wiring here — that is the learn step (P9-03), a non-goal.
- **Recall node stays `dict` single-writer `{"memory": ctx}`** (no reducer — one writer), matching
  the `MemoryContext` slot already reserved on `AgentState` (P4-01).
- **Unbound default node is sync** (unlike RAG's async default) because recall *always* runs, so
  the import-time module graph must remain synchronously invokable — a root-cause fix after the
  first run surfaced `test_guardrail_stubs_populate_allowed_verdicts` failing on a sync `.invoke`.
- **Fail-soft posture mirrors RAG/market**: the store propagates errors; the recall node wraps the
  whole read and returns an empty `MemoryContext`. Guests / malformed user ids never touch the DB.

## How to verify
- `cd backend && .venv/bin/python -m pytest tests/test_memory_agent.py -q`
- Lint/type: `.venv/bin/ruff check app tests` · `.venv/bin/mypy app`

## Tests (final step — mandatory)
- `pytest tests/test_memory_agent.py` → **16 passed**.
- Full suite `pytest` → **770 passed, 66 skipped** (skips are the ML-excluded curated-CI set).
- `ruff check app tests` → All checks passed. `mypy app` → no issues in 136 files.
- One failure was hit and root-caused mid-run: making the unbound recall default async broke a
  sync-graph invoke test; fixed by keeping the default node sync (recall always runs). Also
  renamed the store method `search`→`search_memories` to avoid clashing with `BaseStore.search`'s
  signature (mypy override error). Both are code fixes, not test weakening.

## Self-check
- [x] Meets acceptance criteria (adapter + prefs/memories populate; empty defaults; guest empty;
      fail-soft; wired via existing DI; unit tests for all four cases).
- [x] No secrets; Router→Service→Agent/Repo layering respected (store is repo-facing infra; node
      is agent-layer; reuses the `search_user_memories` primitive — no hand-rolled pgvector query).
- [x] Tests/lints/types pass (pasted above).
