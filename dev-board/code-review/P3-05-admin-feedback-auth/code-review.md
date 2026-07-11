# Code review — P3-05-admin-feedback-auth · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | app/services/feedback.py:52 vs app/repositories/feedback_store.py:39 | `InMemoryFeedbackReader` clamps with `max(0, limit)` while `PostgresFeedbackReader` uses `max(1, limit)`. Cosmetic divergence; endpoint already enforces `ge=1`/`le=1000`, so neither path can receive an out-of-range value. | Optional: align the two clamps (or drop them, since the query param is validated). No behavior impact. |
| C2 | nit | app/repositories/feedback_store.py:38 | Same-`created_at` tiebreaker is `id DESC` on a random-UUID PK — deterministic but not insertion order. Already understood/documented (this is what the engineer's test-fix in the report addresses). | None required; note only. |

## Notes
Verified locally against the actual diff:
- `ruff` + `mypy` clean on all six changed P3-05 modules; `pytest tests/test_admin_feedback_api.py tests/test_feedback_reader.py tests/test_user_store.py` → 12 passed.
- Alembic chain is a single linear head (0001→0005); `0005` revises `0004`, adds `users.is_admin` (Boolean, NOT NULL, `server_default false`), reversible `downgrade` drops it — existing rows backfilled without a data migration.

Correctness / security (all confirmed):
- **No query-string secret auth anywhere in v2.** `main.py` registers only chat/auth/feedback routers; grep for `query_params`/`Query(...key)` in `backend/app` is empty. The v1 root `app.py` (`GET /get-feedback?key=`) is not even tracked on this branch, so criterion 1 is fully met. `test_unauthenticated_is_denied` also asserts `?key=some-token` → 401.
- **Fail-closed authz.** `require_admin` denies when `current_user.user_id is None` (guest) or `is_admin` is false; `PostgresUserStore.is_admin` returns `False` on a malformed UUID (caught `ValueError`) and on a missing row (`scalar_one_or_none`) — never raises. Guest→403, non-admin user→403, missing/unknown→403.
- **401 vs 403 layering correct.** `require_admin` composes on `require_auth`, so no/invalid token is a 401 (with `WWW-Authenticate: Bearer`) before the admin check runs; an authenticated non-admin is a uniform 403. Matches the design ref ("checked via the same session-JWT verify dependency from P3-02").
- **No self-service escalation.** Grep confirms no route/service writes `is_admin`; the only reads are the port method and the SELECT. Grant/revoke is out-of-band SQL, documented in `docs/admin-access.md` and the migration docstring. `server_default false` → new accounts are never admin.
- **Per-request DB check (not carried in the JWT)** so a revoke takes effect on the next request — sound, and the extra indexed-PK lookup per admin call is acceptable.
- **Layering / DRY respected.** Router is thin (owns the gate + response shape, imports only the port/schemas/deps); reads go through the `FeedbackReader` port with the Postgres adapter in the repo layer; admin authz reuses the single `UserStore` `users`-table port (one new `abstractmethod`, both impls updated). SSO builder now reuses `build_user_store` via the extracted `_require_pg_provider` helper. No driver types leak into `api/`.
- SQLAlchemy-core queries are parametrized — no injection surface. No secrets committed. `app.state` keys go through the `AppStateKeys` StrEnum (drift-safe convention).

Acceptance criteria: all five met, with tests covering admin-reads / non-admin-403 / guest-403 / unauthenticated-401 / limit validation (422). Test doubles injected via dependency overrides so no Postgres/Redis runs in unit tests; live-DB path auto-skips.

The two nits are cosmetic and do not gate.
