# Engineer report — P9-05-memory-crud-api · Revision 1

## Summary
Implemented the `/api/memory` panel API (the §5.4/§6.10 transparency-&-control surface,
silent-but-viewable/deletable / opt-out). A logged-in user can view + edit their explicit
`preferences`, view their inferred `user_memories`, delete one, and bulk-clear all. Guests are
rejected (durable-only surface). No per-fact confirmation workflow — edits/deletes are immediate.

Layering: Router (`api/memory.py`) → `MemoryService` → two ports (`PreferenceStore` +
`UserMemoryStore` via a structural `LearnedMemoryStore` Protocol) → repository primitives.

## Files changed
- `app/api/memory.py` (new) — thin router: `GET /api/memory`, `PUT /api/memory/preferences`,
  `DELETE /api/memory/{memory_id}` (204/404), `DELETE /api/memory` (bulk clear). Guest→403 via
  `_require_user` (mirrors dashboard); identity always from the token subject.
- `app/services/memory.py` (new) — `MemoryService` (view/update_preferences/delete/clear) +
  `LearnedMemoryStore` Protocol (DIP seam so tests inject a fake). Owns the typed⇄dict + str→UUID
  boundary so both stores stay thin.
- `app/schemas/memory.py` (new) — `Preferences` (typed, length-capped §5.4 fields), `LearnedMemory`
  (no embedding), `MemoryView`, `ClearMemoriesResponse`.
- `app/services/preferences.py` (new) — `PreferenceStore` ABC + `InMemoryPreferenceStore` (mirrors
  `ProfileStore` idiom).
- `app/repositories/preference_store.py` (new) — `PostgresPreferenceStore` (get/upsert on
  `preferences`, `ON CONFLICT (user_id)` upsert; mirrors `PostgresProfileStore`). This is the
  missing **write** path for `preferences` (only a read path existed, in account export + recall).
- `app/repositories/vector_search.py` — added `UserMemoryListItem` projection +
  `list_user_memories` (plain non-vector SELECT, newest-first, no embedding) + `clear_user_memories`;
  extended `delete_user_memory` with an optional `user_id` to make deletes ownership-scoped
  (learn step keeps its unscoped call).
- `app/memory/store.py` — added `UserMemoryStore.list_memories` / `delete_memory_for_user` /
  `clear_memories` wrapping the new primitives (each commits its own txn).
- `app/app_state.py`, `app/bootstrap.py`, `app/main.py` — `MEMORY_SERVICE` key, `build_memory_service`
  builder (lazy embedder — never model-loads on the CRUD paths), router registration.
- `tests/test_memory_api.py` (new) — API/unit tests over in-memory stores.
- `tests/test_memory_store_postgres.py` (new) — live-DB integration for list/scoped-delete/clear.

## Key decisions
- **Ownership-scoped delete over adding a whole new primitive.** Extended `delete_user_memory`
  with an optional `user_id` instead of a parallel function — the learn step's existing unscoped
  call is untouched, and the API gets `404` (not `403`) for an id it doesn't own (§7 no-leak,
  matching dashboard/message_feedback). [task AC: delete someone else's → 404]
- **Typed, bounded preferences** (not free-form blob) — named §5.4 fields with length/list caps
  for a clear write contract + abuse bounds; unknown stored keys are ignored on read (forward
  compatible), mirroring the `ProfileSchema` both-ways typing. `preferences` stays the
  authoritative signal.
- **Preferences via its own port** (`PreferenceStore` + Postgres adapter) rather than a
  vector_search primitive — `preferences` is identity, not pgvector; the `ProfileStore`
  precedent is the exact structural match (one JSONB row per user).
- **Explicit edits override inferred memories (§5.4 pt 4): confirmed, not re-implemented.**
  `app/agents/memory_agent.py::recall` reads `preferences.data` separately and returns
  `MemoryContext(preferences=…, memories=…)` — preferences is injected alongside/ahead of
  memories in recall (P9-02). This task only edits that same `preferences` row; the override
  semantics already hold. No recall/learn pipeline changes.

## How to verify
- Unit/API: `cd backend && .venv/bin/python -m pytest tests/test_memory_api.py -q`
- Integration (live DB): `DATABASE_URL=postgresql+asyncpg://<creds>@localhost:5432/career_coach \
  .venv/bin/python -m pytest tests/test_memory_store_postgres.py -q`
- Lint/type: `.venv/bin/ruff check app/...` · `.venv/bin/mypy app/...` (both clean)

## Tests (final step — mandatory)
- `pytest tests/test_memory_api.py tests/test_memory_store_postgres.py` → **11 passed, 2 skipped**
  (skips = no test-DB creds); with live DB URL → **13 passed**.
- Full suite (live DB): `pytest -q` → **903 passed, 1 skipped** (pre-existing skip).
- `ruff check` (changed files) → all pass; `mypy` (9 changed source files) → success, no issues.
- One mypy fix during dev: `result.rowcount` on an async `delete` needs a `CursorResult` cast;
  `vector_search.py` already imports `sqlalchemy.cast`, so `typing.cast` was aliased `type_cast`
  and `CursorResult` put under `TYPE_CHECKING` (no runtime import). Not a test defect.

## Self-check
- [x] Meets acceptance criteria (view w/ data, view empty, guest 403, update prefs, delete own 204,
      delete other's → 404, delete unknown → 404, bulk clear leaves prefs; embeddings excluded).
- [x] No secrets committed; Router→Service→Repository layering respected (services never touch the
      driver; repository primitives own SQL; caller commits).
- [x] Tests/lints/types pass (results above).
