# Code review — SEC-05-gdpr-erasure-export · engineer revision 2

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| — | — | — | No new findings. Rev-1 C1/M1/N1 all resolved (see Notes). | — |

## Notes — verification of the rev-1 blocker fix
- **C1 (blocker) — RESOLVED. There is now a real source-of-truth for "all live sessions
  for this user", and `DELETE /api/me` uses it.** The `SessionStore` port gained
  `list_user_sessions(user_id)` and is documented as the authoritative live-session registry
  (`services/session_store.py:31-74`). `RedisSessionStore` maintains a per-user Redis **set**
  index at `session:user:<user_id>`: `create` SADDs the id + refreshes the set TTL whenever
  `record.user_id` is set; `delete` reads the record first then SREMs; `list_user_sessions`
  returns `smembers` (`repositories/redis.py:269-308`). `AccountService.erase` now enumerates
  from this index and revokes each record **before** the Postgres cascade
  (`services/account.py:79-81`). The old Postgres-backed `AccountRepository.list_session_ids`
  is fully removed — confirmed `grep list_session_ids app/ tests/` returns nothing.
- **The index is actually populated on the real login paths** (this was the crux of C1).
  Both writers go through `SessionStore.create` with a `user_id`-bearing `SessionRecord`:
  plain login `SsoAuthService._resolve_session` (`services/auth.py:284-292`) and guest→account
  upgrade `GuestUpgradeService.upgrade` (`services/guest_upgrade.py:165-173`). So a
  just-logged-in device that never persisted a chat turn (hence no Postgres `sessions` row) is
  in the index and gets revoked — exactly the gap that failed rev 1.
- **Wiring matches namespaces.** Every `RedisSessionStore` in `bootstrap.py` (auth, upgrade,
  account, etc.) is built via `from_settings(...)` over the same shared Redis client with the
  default `key_prefix="session:record"` / `index_prefix="session:user"`, so the store the
  authenticator/login writes to is the same namespace `AccountService` enumerates and revokes.
  The store is stateless (client + fixed prefixes), so a fresh instance per service is fine.
- **M1 (minor) — RESOLVED by construction.** Revocation now reads-then-revokes from the single
  live Redis index; the old two-transaction Postgres-vs-Redis enumeration window is gone.
- **N1 (nit) — RESOLVED.** Tests now exercise the login-shaped case with **no** Postgres
  `sessions` row: `test_me_api.test_delete_me_erases_and_revokes_all_sessions` seeds sessions
  store-only and asserts both `s1`/`s2` are revoked; `test_session_store.py` adds real set-op
  coverage (index populated by `create`, guests not indexed, `delete` de-indexes, erase-shaped
  enumerate-then-revoke clears every device). The `FakeStringRedis` fake implements real
  `sadd/srem/smembers` set semantics, so the index assertions are not vacuous. 24 unit tests
  pass locally (`test_session_store` + `test_account_service` + `test_me_api`).
- **feedback.contact PII scrub (system-architect follow-up) — good, and correctly scoped as a
  correctness/privacy fix.** `delete_user` now runs `UPDATE feedback SET contact = NULL` in the
  **same transaction** as the `DELETE FROM users` cascade (`repositories/account.py:104-107`),
  so the deliberately-retained (`ON DELETE SET NULL`) product-feedback row is left truly
  anonymous. Covered by `test_delete_user_scrubs_feedback_contact` (row survives with
  `user_id`/`contact` NULL, `content` intact) and the export test still returns the owner's own
  `contact` (Art. 20). Idempotent (unknown id scrubs zero rows).
- **Unchanged-and-still-good from rev 1** (re-confirmed against current source): DB-level
  cascade completeness across every user-owned table; export strictly `user_id`-scoped with raw
  `embedding` columns never in the SELECT lists and shared `user_id IS NULL` KB rows excluded;
  auth-required + guest→403; idempotency (malformed/unknown id → no-op, never 500); BFF
  catch-all passthrough. No regressions introduced by the rev-2 changes.

All six acceptance criteria are now met and verifiable.
