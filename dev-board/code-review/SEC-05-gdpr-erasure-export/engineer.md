# Engineer report — SEC-05-gdpr-erasure-export · Revision 2

## Revision 2 summary (what changed since rev 1)
- **C1 (blocker) — session revocation now enumerates the authoritative Redis registry, not
  Postgres.** The `sessions` Postgres table is only lazily populated (first persisted turn), so
  a just-logged-in device had no row and its Redis session record was never revoked. Fixed by
  making the **`SessionStore` the authoritative source of truth**: it now maintains a per-user
  session index (a Redis set `session:user:<user_id>`) written on every logged-in `create`
  (login `SsoAuthService._resolve_session` and guest-upgrade both go through `SessionStore.create`
  with a `user_id`-bearing record), cleaned on `delete`, and enumerated by a new
  `list_user_sessions(user_id)` port method. `AccountService.erase` now revokes every session from
  that index, so all devices are revoked regardless of whether a Postgres row was ever written.
  Removed the wrong `AccountRepository.list_session_ids` (Postgres) path entirely.
- **M1 (minor) — closed by construction.** Revocation now reads-then-revokes from the live Redis
  index in the same flow, so there is no Postgres-vs-Redis enumeration gap.
- **N1 (nit) — real login-shaped coverage added.** New `test_session_store.py` cases assert the
  index is populated by `create` (no Postgres row involved), guest sessions are *not* indexed,
  delete removes from the index, and an erase-shaped enumerate-then-revoke clears every device.
  `test_me_api` / `test_account_service` now seed sessions **only** in the store (the login-shaped
  case) and assert revocation.
- **system-architect follow-up (feedback.contact PII) — fixed now (not deferred).** `feedback` is
  `ON DELETE SET NULL` by design (product feedback outlives the account), but its `contact` column
  is a user-typed email — directly-identifying PII that a plain SET NULL leaves behind. `delete_user`
  now scrubs `feedback.contact` to NULL in the **same transaction** as the cascade, so the detached
  row is truly anonymous (content retained, contact + user_id gone). One-line, cheap, and it makes
  erasure actually anonymize per Art. 17. Covered by a new live-DB test.

## Files changed in revision 2
- `backend/app/services/session_store.py` — `SessionStore` port gains `list_user_sessions`;
  `InMemorySessionStore` maintains a per-user index on create/delete.
- `backend/app/repositories/redis.py` — `RedisSessionStore` maintains the `session:user:<id>` set
  (SADD+EXPIRE on user `create`, SREM on `delete`) and implements `list_user_sessions`; `StoreRedis`
  protocol gains `sadd`/`srem`/`smembers`/`expire`.
- `backend/app/services/account.py` — `erase` enumerates from the `SessionStore` (authoritative),
  not the repo; dropped `AccountRepository.list_session_ids` and its in-memory impl.
- `backend/app/repositories/account.py` — dropped `list_session_ids`; `delete_user` now scrubs
  `feedback.contact` before the cascade.
- Tests: `test_session_store.py` (+6 index cases, fake gains set ops), `test_account_service.py`
  / `test_me_api.py` (seed via store only), `test_account_repository_postgres.py` (drop
  `list_session_ids`, add `feedback.contact` scrub test + export-includes-contact assertion).

## Revision 2 verification
- `ruff check` + `ruff format --check`: clean. `mypy app/`: **Success, no issues (95 files)**.
- `uv run --no-sync pytest` (integration skipped): **472 passed, 53 skipped**.
- `make test-integration-full` (real Postgres, up→migrate→run→down): **524 passed, 1 skipped**
  (the 1 skip is the pre-existing ML-dep test) — exercises the real cascade, the new
  `feedback.contact` scrub, export scoping/embedding-exclusion.
- Frontend unchanged this revision (BFF passthrough already covered in rev 1).

---

# Engineer report — SEC-05-gdpr-erasure-export · Revision 1

## Summary
Implemented `DELETE /api/me` (GDPR Art. 17 erasure) and `GET /api/me/export` (Art. 20
portability) per §7.6/§9, logged-in users only. Erasure revokes **all** of the user's live
Redis sessions (every device), then deletes the `users` row — which cascades the entire
Postgres footprint via the existing P2 `ondelete="CASCADE"` FKs. Export returns a single
caller-scoped JSON document (downloadable attachment) covering every user-owned table,
excluding raw `vector(4096)` embeddings. Layering: Router (`api/me.py`) → Service
(`services/account.py`) → Repository (`repositories/account.py` + Redis `SessionStore`).

## Files changed
- `backend/app/schemas/account.py` — new. `AccountExport` model (sections as JSON-safe row
  dicts; no embedding field exists in the shape).
- `backend/app/services/account.py` — new. `AccountRepository` port + `InMemoryAccountRepository`
  double + `AccountService` (orchestrates Redis revocation then Postgres cascade; export passthrough).
- `backend/app/repositories/account.py` — new. `PostgresAccountRepository`: single cascade
  `DELETE FROM users`, `list_session_ids`, and per-table scoped `SELECT`s (explicit columns —
  embeddings never selected; UUID/date/datetime coerced to JSON-safe strings).
- `backend/app/api/me.py` — new. Thin router; `require_auth`, guest→403, 204 on delete,
  `Content-Disposition: attachment` on export.
- `backend/app/bootstrap.py` — `build_account_service` (Postgres repo + shared Redis session store).
- `backend/app/app_state.py` — `ACCOUNT_SERVICE` key.
- `backend/app/main.py` — register `me_router`.
- `backend/tests/test_account_service.py`, `test_me_api.py`,
  `test_account_repository_postgres.py` — new test suites.
- `frontend/__tests__/bffProxy.test.ts` — added DELETE `/api/me` + GET `/api/me/export`
  passthrough cases (verifies the SEC-04 catch-all handles both with no frontend change).

## Key decisions
- **Redis revocation before Postgres delete** (§7.6, task point 1): the Postgres `sessions`
  cascade does not touch the separate Redis session records the live JWT check reads, and the
  cascade would erase the rows telling us *which* Redis keys to clear — so `AccountService.erase`
  reads `sessions.id` for the user, deletes each Redis record, then deletes the `users` row.
  Depends on the existing `SessionStore` port (not the authenticator) to stay in the ports layer.
- **Single cascade delete, no hand-written per-table deletes** — relies on the P2 FKs; idempotent
  (unknown/malformed id → 0 rows / no-op, never a 500).
- **Export via explicit-column SELECTs** — naturally excludes `kb_chunks.embedding` /
  `user_memories.embedding` (§7.6) and makes caller-scoping explicit (direct `user_id` filter, or
  join through an owned parent: messages→conversation, chunks→document, milestones/tasks→goal).
  Shared/curated `user_id IS NULL` KB rows are never selected.
- **Export shape = sections of open row dicts** (not 14 typed row models): a portability dump, not
  a field-by-field API — KISS, and keeps one place (the `SELECT`) governing which columns leave.
- **Guest → 403** (consistent with `PUT /api/profile`); **DELETE → 204** (consistent with
  `POST /api/auth/logout`); export served as a download attachment.
- **Celery-held artifacts = accepted residual** (task point 2): CV bytes are never persisted
  durably (only the structured `profiles.data`, which cascades); the Celery result backend has no
  `task_id → user_id` index (documented tradeoff in `api/jobs.py`) and self-expires via
  `result_expires` TTL. No new tracking infra built — bounded residual, consistent with §6.17/§6.18.
- **BFF**: the SEC-04 catch-all Route Handler is fully generic over method/path; both endpoints
  flow through unchanged (verified by new tests — Authorization injected, `Content-Disposition`
  survives the passthrough). No frontend code change needed.

## How to verify
- Backend unit/API + full suite: `cd backend && make test` (integration suites skip without a DB).
- Live-DB cascade/scoping/embedding-exclusion: bring up the db, migrate, run
  `test_account_repository_postgres.py` (commands in Tests below).
- Frontend BFF: `cd frontend && npx jest bffProxy`.

## Tests (final step — mandatory)
- Backend, against **real Postgres** (brought up the db via the dev-ports override, `alembic
  upgrade head`, then torn down after):
  - `pytest` full suite: **517 passed, 1 skipped** (the 1 skip is a pre-existing ML-dep test).
  - New suites specifically: `test_account_service.py` + `test_me_api.py` (11 passed) and
    `test_account_repository_postgres.py` (**3 passed** against live DB — exercises the real
    cascade, cross-user + shared-KB scoping, and embedding exclusion; skips cleanly with no DB).
- `ruff check` (app + new tests): **All checks passed**; `ruff format`: clean.
- `mypy app/`: **Success: no issues found in 95 source files**.
- Frontend `npx jest`: **13 suites, 116 tests passed** (incl. the 2 new BFF cases). One initial
  BFF assertion was wrong (expected `undefined` body for a bodyless DELETE; the proxy correctly
  forwards the request's `null` body for non-GET) — fixed the test assertion, not the proxy.

## Self-check
- [x] Meets acceptance criteria (cascade + all-device Redis revocation; idempotent; scoped export
      excluding embeddings; auth-required + guest-rejected; reachable through the BFF catch-all).
- [x] No secrets committed; Router→Service→Repository layering respected (service depends only on
      ports; router is thin; SQL lives in the repository).
- [x] Tests/lints/typecheck pass (results pasted above).

---

## Response to review (revision 2)

### Code review
- **C1 (blocker) — Session revocation enumerated the wrong (lazily-populated Postgres) registry.**
  Fixed. The authoritative source of truth for "all live sessions for this user" is the Redis
  `SessionStore` — a session exists there from login, before any Postgres `sessions` row is
  lazily written on the first persisted turn. I added a **per-user session index** to the store
  (Redis set `session:user:<user_id>`): `RedisSessionStore.create` SADDs the id + refreshes the
  set's TTL whenever `record.user_id` is set (which is the case for both login via
  `SsoAuthService._resolve_session` and guest-upgrade via `GuestUpgradeService.upgrade`, since both
  call `SessionStore.create` with a user-bearing record), `delete` SREMs it, and a new
  `list_user_sessions(user_id)` port method enumerates it. `AccountService.erase` now revokes each
  session from that index and then does the Postgres cascade — so every device is revoked even if it
  never persisted a turn (no Postgres row). Removed `AccountRepository.list_session_ids` (the wrong
  Postgres path) and its in-memory impl. New test asserts the real login-shaped case: a session that
  lives **only** in the store (no Postgres row) is revoked (`test_session_store.py`
  `test_user_sessions_are_indexed_and_enumerable` / `test_erasure_revokes_every_indexed_session`;
  `test_me_api.test_delete_me_erases_and_revokes_all_sessions` now seeds sessions store-only).
- **M1 (minor) — two-transaction enumerate/delete gap.** Closed as the reviewer predicted: revocation
  now reads-then-revokes from the single live Redis index, no Postgres-vs-Redis enumeration window.
- **N1 (nit) — live-DB test seeded a Postgres `sessions` row that can't catch C1.** Removed; the
  session-index behavior is now covered by store-level tests that never write a Postgres row.

### Architecture review
- **Follow-up (feedback.contact PII survives SET-NULL erasure) — fixed now, not deferred.** Agreed
  it undercuts Art. 17 anonymization and is a one-liner. `delete_user` now runs
  `UPDATE feedback SET contact = NULL WHERE user_id = :uid` in the **same transaction** as the
  cascade delete, so the surviving (deliberately-retained) product-feedback row is truly anonymous:
  `content` kept, `contact` + `user_id` gone. New live-DB test
  `test_delete_user_scrubs_feedback_contact` asserts the row survives with `user_id`/`contact` NULL
  and `content` intact; the export test asserts the owner still gets their own `contact` back (Art. 20).
  `A4/A11` conformance unchanged otherwise (still Postgres+Redis only, ports-only service).
