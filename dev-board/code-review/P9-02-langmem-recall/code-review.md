# Code review — P9-02-langmem-recall · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/app/agents/memory_agent.py:81 | The final `MemoryContext(preferences=preferences, memories=memories)` construction sits **outside** the try/except. If `preferences.data` JSONB ever held a non-dict (a list/scalar), Pydantic validation would raise out of the node rather than degrading soft. Inputs are trusted today (own `preferences` table, dict by convention, currently schema-only), so no live crash path. | Optionally move the `MemoryContext(...)` build inside the try (or have `_fetch_preferences` coerce non-dict → `{}`) so the fail-soft guarantee is total. Non-blocking. |
| C2 | nit | backend/app/agents/memory_agent.py:73-76 | `recall` opens `db.session()` for the preferences read, closes it, then `store.search_memories` opens a **second** session for the vector search — two round-trip sessions per turn on the hot pre-planner path. Also: when the memory search fails but the prefs read succeeded, the whole context (incl. the valid prefs) is discarded. | Both are acceptable per the acceptance criteria ("any error → empty context") and match the RAG/market fail-soft posture. Flagging only as a future optimization; no change required. |

## Notes
- Acceptance criteria all met and verified: `BaseStore`-conforming `UserMemoryStore` (per-user namespace, search-only; write ops raise a clear `NotImplementedError` marking the P9-03/P9-05 boundary); `recall` populates `preferences` + `memories` for a logged-in user, empty defaults when no data, empty for guest with **no DB touch** (`session.statements == []` asserted), and degrades to empty `MemoryContext` on both DB and embedding failure.
- Security: user scoping is correct and parametrized — `Preference.user_id == user_id` and `search_user_memories(..., user_id=...)` both filter by the UUID parsed from `state.user_id`; guests/malformed ids short-circuit before any query, so no cross-user memory/pref leakage. No secrets. No hand-rolled SQL (reuses the P2-06 `search_user_memories` primitive).
- Wiring verified end-to-end: `build_graph` swaps in the bound recall node when `db` is given, and `bootstrap.py:235-242` already passes `embedder=` + `db=` into `GraphTurnStreamer`, so recall is live in production without a bootstrap change. Graph topology (INPUT_GUARDRAIL → MEMORY_RECALL → PLANNER) unchanged. Sync no-provider default (`{}`) correctly keeps the import-time module graph synchronously invokable.
- Verified locally: `pytest tests/test_memory_agent.py` → 16 passed; `ruff check` clean; `mypy` clean on the 3 changed source files.
- Out of scope for this review: the `identity.py` `UniqueConstraint` + `bootstrap.py` message-feedback changes in the working tree belong to P9-01, not P9-02.
