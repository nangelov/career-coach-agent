---
name: check-langmem-recall-tasks
description: Reviewing P9 memory recall/store tasks (app/memory/store.py + agents/memory_agent.py) — fail-soft totality, per-user scoping, BaseStore boundary, prod wiring
metadata:
  type: project
---

Reviewing P9 teachable-memory tasks (recall P9-02, learn P9-03, CRUD P9-05) over the pgvector
`user_memories` table + `preferences.data` JSONB.

**Why:** these are the first tasks to read/write `user_memories` for real; cross-user leakage and
fail-soft holes are the live risks. `UserMemoryStore(BaseStore)` in `app/memory/store.py` is shared
infra (P9-03/P9-05 subclass it), so its search/write boundary must stay honest.

**How to apply — check on every P9 memory task:**
- **Per-user scoping (security gate):** every read must filter by the UUID parsed from
  `state.user_id` — `Preference.user_id == uid` AND `search_user_memories(..., user_id=uid)`.
  Guests/malformed ids must short-circuit to empty `MemoryContext()` *before any query* (assert
  `session.statements == []` in tests). No hand-rolled pgvector SQL — reuse `search_user_memories`.
- **Fail-soft totality:** "any DB/embedding error → empty context" means the *whole* read incl. the
  final `MemoryContext(...)` construction must be inside try/except. A common gap: building the
  Pydantic context *after* the except block, so a malformed JSONB prefs row (non-dict) raises out.
  Trusted-input today (own tables) → nit, not a gate; flag it.
- **BaseStore boundary:** recall = search only. `abatch` services `SearchOp`; `PutOp/GetOp/list` and
  sync `batch` must raise a clear `NotImplementedError` naming the owning task (P9-03/P9-05), not
  silently no-op. The store propagates errors; the *node* degrades — keep the store a thin data seam.
- **Prod wiring is real, not deferred:** confirm `build_graph` swaps in the bound node when `db`
  given AND `bootstrap.py` GraphTurnStreamer already passes `embedder=`+`db=` (it does) — otherwise
  recall is dead code. Graph topology INPUT_GUARDRAIL → MEMORY_RECALL → PLANNER must be untouched.
- **Sync no-provider default:** the import-time module-graph recall default must stay *sync* (returns
  `{}`) — recall always runs, so an async default breaks sync `.invoke` graph tests. (Unlike the
  conditionally-routed RAG worker whose default is async.)
- Working tree often mixes sibling P9 tasks (P9-01 message-feedback identity.py/bootstrap.py churn);
  scope the review to memory files.

**P9-03 learn task (post-turn Celery) — the recurring defect: thumb-down demotion is not
idempotent.** The learn pass consumes `MessageFeedbackStore.list_recent_downvotes(user_id, limit=N)`,
which returns the N most-recent down-votes with **no processed-marker**. If `_demote_for_message`
has no guard, a *single* down-vote is re-applied on **every subsequent learn pass** (fires once per
later turn) → confidence walks 0.9→0.6→0.3→deleted-at-floor within ~2-3 turns → silent progressive
data loss that defeats the graduated demote-vs-remove design. Gate this (major). Require a test that
runs **two consecutive learn passes** over the same standing down-vote and asserts the memory is
demoted **once**, not driven to deletion. (Note: the current-turn down-vote branch / explicit
"avoid X" preference rarely fires in prod — a fresh turn's learn pass runs before the user can vote —
so the recent-downvote path is the one that actually executes and the one lacking idempotency.)
**Accepted fix (P9-03 rev 2, APPROVED):** timestamp-gate the demotion — `_demote_for_message`
takes the vote's `voted_at` and skips any memory whose `updated_at > voted_at` (strict `>`). A
demotion bumps `updated_at` (server `onupdate=now()`) past the vote so later passes skip it; a fresh
re-vote bumps feedback `created_at` and is re-honoured. No schema change, no processed-marker table.
Meaningful only if the test fake bumps `updated_at` on update (mirroring `onupdate`) — check that.
Don't re-gate this approach.

Otherwise P9-03 was solid: enqueue after awaited/committed `_persist_turn` (satisfies the
`user_memories.source_message_id → messages.message_id` FK), fenced+forced-tool-call extraction,
type-aware dedup, real confidence signal, guest/cancelled/empty/no-enqueuer skip tested.
