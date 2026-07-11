# Engineer report — P3-05-admin-feedback-auth · Revision 1

## Summary
Replaced v1's insecure `GET /get-feedback?key=<HF_TOKEN>` (authenticate-by-matching-the-LLM-
token-in-the-query-string) with real admin access control. Added an `is_admin` flag on the
`users` row (migration `0005`), a reusable `require_admin` FastAPI dependency that checks it
against the P3-02 session JWT, and an admin-only `GET /api/feedback` endpoint that lists
free-text product feedback from Postgres (§4 `feedback` table). No endpoint authenticates via
a shared secret in the query string anymore.

Layering respected (Router → Service/Port → Repository): the router is thin; feedback reads go
through a `FeedbackReader` port (Postgres adapter in the repository layer); admin authz goes
through the existing `UserStore` port (one `users`-table adapter, now shared by SSO upsert and
the admin check).

## Files changed
- `backend/app/repositories/models/identity.py` — add `User.is_admin` (Boolean, NOT NULL,
  `server_default false()`).
- `backend/migrations/versions/20260711_0005_admin_flag.py` — new migration adding
  `users.is_admin`; docstring documents the SQL grant/revoke (no self-service escalation).
- `backend/app/services/user_store.py` — extend `UserStore` port with `is_admin(user_id)`;
  `InMemoryUserStore` grows an `admin_ids` set + `is_admin` (fail-closed default).
- `backend/app/repositories/user_store.py` — `PostgresUserStore.is_admin` (indexed PK lookup;
  malformed/unknown id → `False`, fail-closed).
- `backend/app/schemas/feedback.py` — new `FeedbackEntry` + `FeedbackListResponse` read models.
- `backend/app/services/feedback.py` — new `FeedbackReader` port + `InMemoryFeedbackReader`.
- `backend/app/repositories/feedback_store.py` — new `PostgresFeedbackReader` (newest-first).
- `backend/app/security/dependencies.py` — new `get_user_store` dep + `require_admin` gate
  (composes on `require_auth`; guest/non-admin → 403).
- `backend/app/bootstrap.py` — `build_user_store` + `build_feedback_reader`; extracted
  `_require_pg_provider` helper; SSO builder now reuses `build_user_store` (DRY).
- `backend/app/app_state.py` — `USER_STORE`, `FEEDBACK_READER` state keys.
- `backend/app/api/feedback.py` — new thin router: `GET /api/feedback` gated by `require_admin`.
- `backend/app/main.py` — register the feedback router.
- `docs/admin-access.md` — documented way to grant/revoke admin (SQL `UPDATE users`).
- Tests: `tests/test_admin_feedback_api.py`, `tests/test_feedback_reader.py`,
  `tests/test_admin_feedback_postgres.py` (live-DB, auto-skips); extended `tests/test_user_store.py`.

## Key decisions
- **`is_admin` checked per-request against the DB, not carried in the JWT.** Keeps privilege
  out of the (short-lived, revocation-only) token so a revoke takes effect on the next request,
  and matches the design ref ("checked via the same session-JWT verify dependency from P3-02").
  The `require_admin` dependency composes on `require_auth` → so 401 (no/invalid token) is
  distinguished from 403 (authenticated but not admin). Design ref: §7 AuthZ.
- **Admin lookup lives on the existing `UserStore` port**, not a second user-table adapter —
  DRY/SoC: `UserStore` is *the* `users`-table port. Added one `abstractmethod`; only two impls
  exist (`InMemoryUserStore`, `PostgresUserStore`), both updated in the same pass.
- **Fail-closed authz.** Unknown/malformed user id and missing rows resolve to `is_admin=False`;
  a guest (no `user_id`) can never be admin.
- **No self-service escalation.** No route sets `is_admin`; granted only out-of-band by an
  operator with DB access (documented). `server_default false` → new accounts are never admin.
- **Read-only feedback port (YAGNI).** `FeedbackReader` exposes only `list_feedback` — the
  `POST /api/feedback` submit path is a separate task and out of scope here.
- **`GET /api/feedback` is the v2 read endpoint** (the §9 API table lists `POST /api/feedback`
  for submit; the admin read is the direct replacement for v1's `GET /get-feedback`). Response
  is a `FeedbackListResponse` wrapper (not a bare array) so paging can be added non-breaking.

## How to verify
- Lint: `cd backend && .venv/bin/ruff check app/ migrations/ tests/` → all pass.
- Types: `.venv/bin/mypy app/ migrations/` → success, 68 files.
- Unit: `.venv/bin/pytest -q` → 192 passed, 43 skipped (integration auto-skips without a DB).
- Integration (live DB): apply `alembic upgrade head` (adds 0005), then run the suite with the
  live `DATABASE_URL` → 235 passed. Manual: grant admin via
  `UPDATE users SET is_admin = true WHERE email = '…';` and call `GET /api/feedback` with that
  user's bearer token (200); a non-admin/guest token → 403; no token → 401.

## Tests (final step — mandatory)
- `cd backend && .venv/bin/ruff check app/ migrations/ tests/` → **All checks passed!**
- `.venv/bin/mypy app/ migrations/` → **Success: no issues found in 68 source files**
- `.venv/bin/pytest -q` (no DB) → **192 passed, 43 skipped**
- Live DB (`alembic upgrade head` applied 0004→0005; `DATABASE_URL` set from root `.env`):
  `.venv/bin/pytest -q` → **235 passed** (all integration tests exercised).
- **One test bug found and fixed (test, not code):** the first pass of
  `test_admin_feedback_postgres.py::test_list_feedback_newest_first` inserted three rows in a
  single transaction and asserted insertion order. Root cause: Postgres `now()` is constant
  within a transaction, so all three rows shared one `created_at`; the adapter's same-timestamp
  tiebreaker is `id DESC` (random UUID), so insertion order is not preserved. Fixed the *test*
  to write explicit, spaced `created_at` values (the ordering contract the adapter actually
  guarantees). The implementation ordering (`created_at DESC, id DESC`) is unchanged.

## Self-check
- [x] Meets acceptance criteria: no query-string-secret auth remains; `GET /api/feedback`
      requires an authenticated admin session; non-admin and unauthenticated are denied
      (403/401); admin grant documented (migration + `docs/admin-access.md`); tests cover
      admin-reads / non-admin-denied / guest-denied / unauthenticated-denied.
- [x] No secrets committed; Router→Service/Port→Repository layering respected (router imports
      no driver types; DB access only via the shared Postgres provider).
- [x] Tests/lints pass (results pasted above).
