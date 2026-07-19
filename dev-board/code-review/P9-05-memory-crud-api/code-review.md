# Code review — P9-05-memory-crud-api · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | app/schemas/memory.py:53-61 | `tone`/`formality`/`language` are free strings (≤64 chars) that recall (P9-02) injects into the caller's own prompt — no allowlist/enum. Self-scoped (a user only steers their own coach), so not a cross-user injection risk, but unbounded free text. | Optional: constrain to enums/known values if these values ever influence more than the caller's own turn. No change required now. |
| C2 | nit | app/repositories/vector_search.py:list_user_memories | `list_user_memories` caps the panel view at `limit=200` while `clear_user_memories` is unbounded — an account with >200 memories sees a truncated panel yet "clear all" still deletes everything. | Fine for realistic accounts (few memories); note only. |
| C3 | nit | app/schemas/memory.py:44 | `Preferences` relies on pydantic's default `extra="ignore"`, so a `PUT` with a mistyped key is silently dropped (no 422). Intentional (forward-compatible read), documented in the module docstring. | None — acceptable trade-off. |

## Notes
- **Security / ownership scoping (the core risk for this surface): clean.** Owner is always the verified token subject — no path/body `user_id` anywhere. Guests → `403` before any work (`_require_user`, mirrors dashboard). Delete/list/clear are all scoped by `user_id`: `delete_memory_for_user` and the `delete_user_memory(user_id=…)` primitive return `False`/`404` for an id that is unknown, malformed, *or* owned by another user — uniform `404`, no ownership leak. Verified against real Postgres in `test_memory_store_postgres.py` (user B refused user A's row; clear removes only the caller's rows).
- **Embeddings never cross the wire** (§7.6): `UserMemoryListItem`/`LearnedMemory` projections carry only display columns; the 4096-dim vector stays in the DB. Asserted in `test_view_returns_preferences_and_memories_without_embeddings`.
- **No confirmation workflow (§6.10):** PUT/DELETE are immediate. Correct for the opt-out surface.
- **Fail-safe parsing:** malformed `user_id`/`memory_id` → `None` → empty result / `404`, never raises (`_as_uuid`, `PostgresPreferenceStore.get`).
- **Layering (§8) respected:** Router (HTTP only) → `MemoryService` (validate/serialize + str→UUID boundary) → `PreferenceStore`/`LearnedMemoryStore` ports → repository primitives (own SQL, caller commits). `LearnedMemoryStore` Protocol is a clean DIP seam for the test fake. Upsert uses `ON CONFLICT (user_id)` (no SELECT-then-branch race) and sets `updated_at` explicitly (Core upsert bypasses ORM `onupdate`).
- **Bootstrap wiring is live**, not deferred: `MEMORY_SERVICE` key, `build_memory_service` (`_require_pg_provider` fails loudly, lazy embedder never model-loads on CRUD paths), router registered in `main.py`.
- **Acceptance criteria fully met** and each is test-backed: view-with-data / view-empty / auth 401 / guest 403 / PUT upsert (immediate) / delete own 204 / delete other's 404 / delete unknown 404 / malformed id 404 / bulk clear leaves preferences. §5.4-pt4 override is correctly confirmed-not-reimplemented (recall reads the same `preferences` row this task edits).
- Verified locally: `pytest tests/test_memory_api.py` → 11 passed; `ruff` + `mypy` on the 7 changed source files → clean. (Live-DB integration test skips without creds, as designed.)
- The working tree bundles sibling P9 tasks (P9-01 message-feedback, P9-03 learn); this review is scoped to the memory-panel files only.
