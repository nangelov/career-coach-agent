# Code review — P5-05-profile-crud · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | app/repositories/profile_store.py:69 | `upsert` calls `uuid.UUID(user_id)` with no guard, whereas `get` (line 46-48) fail-safes a malformed id to `None`. A non-UUID `user_id` here would raise `ValueError` → 500. Not a live risk (the caller passes the verified token subject, always a real `users.id` UUID; a guest is already rejected upstream), so it is an internal asymmetry only. | Optional: no change required. If touched later, either mirror the `get` guard or add a comment that the caller guarantees a valid UUID (the docstring already states this). |
| C2 | nit | app/api/profile.py:204-226 | `PUT` is full-replace: because every `ProfileSchema` field defaults to empty, a body that omits a section (e.g. `{"skills": [...]}`) silently nulls `experience`/`education`/`goals`. This is correct REST PUT semantics and matches the task ("replace/update"), but is a data-loss footgun for the P5-07 edit UI. | No change required for this task. Note for P5-07: the edit UI must submit the complete profile, or a future PATCH/merge variant should be considered. |

## Notes
- Correctness: GET/PUT are strictly user-scoped — the target row is always `current_user.user_id` (verified token subject); there is no path/query `user_id` a caller could point at another user (§7 AuthZ). Guest handling is explicit and safe (GET → empty `200` with no DB hit, PUT → `403`), so no guest path falls through to a 500.
- Upsert is atomic (`INSERT ... ON CONFLICT (user_id) DO UPDATE`), matching the `unique` constraint on `profiles.user_id`; `updated_at=func.now()` is set explicitly on the conflict path (the ORM `onupdate` hook does not fire for a Core `on_conflict_do_update`) — correct. No SELECT-then-branch race.
- Security: parameterized SQLAlchemy Core/ORM only (no injection); no secret leakage; malformed body → `422` via FastAPI schema validation before the handler runs; no untrusted content reaches tools/SSRF surface. `require_auth` gates both endpoints (missing-token → `401` verified by test).
- Layering: clean Router → Service(port) → Repository(adapter). SQLAlchemy is imported only in `app/repositories/profile_store.py`; the router/port never touch the ORM. Port/adapter mirrors the established `UserStore`/`FeedbackReader` idiom, and reuses the authoritative `ProfileSchema` (P5-03) as the wire contract rather than redefining a parallel DTO (DRY, correct per task).
- Lazy-DI (`get_profile_store`) is the same check-then-build pattern as the existing profile-ingest/user stores; a concurrent double-build is harmless because `PostgresProfileStore` wraps the already-built shared `PostgresConnectionProvider` (no new pool). No gating race.
- Tests: `test_profile_api.py` covers get-none→empty, get-with-profile, put-creates, put-updates, cross-user isolation, guest GET/PUT, malformed-body `422`, and missing-auth `401`. `test_profile_store_postgres.py` adds a live-DB-gated round-trip (insert/replace/one-row + malformed-id) with the P2/P5 reachability-skip convention. Verified locally: `pytest tests/test_profile_api.py tests/test_profile_store_postgres.py` → 9 passed, 2 skipped (no local Postgres); `ruff check` and `mypy` clean on the three new modules.
- All acceptance criteria met.
