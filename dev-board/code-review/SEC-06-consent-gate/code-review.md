# Code review — SEC-06-consent-gate · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/app/repositories/user_store.py:64-79 | `upsert` writes `consent_*` on the conflict-update branch unconditionally, so a caller passing the `None` defaults would clobber an existing user's recorded consent to NULL. No such caller exists today (the only `user_store.upsert` caller is the SSO `complete_login`, which always passes real values), so this is latent, not live. | If a non-login upsert path is ever added, guard the update (e.g. `COALESCE`/only-set-when-provided) so it can't erase a prior consent. No change required now. |
| C2 | nit | frontend/components/UpgradePrompt.tsx:57; frontend/lib/auth.ts:186 | Guest→account upgrade auto-threads `consent:true` and the backend stamps the *current* `CONSENT_POLICY_VERSION`, so an upgrading guest is recorded as accepting whatever version is current at upgrade time without a fresh explicit checkbox — even if the policy bumped between guest-start and upgrade. | Documented scope boundary (engineer.md "Key decisions"; re-prompt happens at next login). Acceptable; noted only. |

## Notes
Verified against the task's four focus areas:

- **Server-side enforcement (not just a disabled button).** Enforcement lives in the services, not the router: `GuestAuthService.create_guest_session` raises `ConsentRequired` before minting anything (`services/auth.py`), and `SsoAuthService.begin_login` raises `ConsentRequired` **before** writing the OAuth-state record and **before** consuming any upgrade ticket. The API layer (`api/auth.py`) only maps `ConsentRequired → 400`. The disabled buttons in `Login.tsx` are pure UX; removing them cannot bypass the gate. The BFF `guest/route.ts` reads consent from the browser body and forwards it (fail-closed on missing/invalid body); `login/[provider]/route.ts` forwards `request.nextUrl.search` (carrying `consent=1`) and surfaces backend 400 → `login_error=consent_required`.
- **OAuth-state carries consent with no bypass.** `begin_login` rejects before persisting the state record, so every stored `OAuthStateRecord` already has `consent_policy_version` set; `complete_login` reads it from the *server-minted, single-use* state record (not from any client input) and stamps `consent_accepted_at=now`. The accepted version comes from server config, not the client (client only conveys a boolean), so a crafted callback cannot forge acceptance of an arbitrary version. `consent=1` is coerced to `True` by FastAPI's bool query parsing; absent/`0` → default `False` → rejected.
- **Migration correctness.** `0006` revises `0005` (confirmed single head, no `0007`); both columns nullable, no server default (existing rows backfill NULL, no data migration); `upgrade` adds both, `downgrade` drops in reverse order. Model (`identity.py`), service DTO (`UserAccount`), and repo writes are all in sync.
- **Guest-session gate.** `POST /api/auth/guest` requires `{"consent": true}`; a missing body is treated as `consent=false` (fail closed → 400, no Redis record written — asserted in `test_guest_endpoint_rejects_missing_consent`). Accepted version is stamped on the transient `SessionRecord` (serialized via `model_dump_json`), consistent with §6.18 (guests hold nothing durable).

**Re-prompt on version bump** is satisfied by re-recording on every login (`test_complete_login_records_current_policy_on_returning_stale_user`), matching the documented "re-prompt = next login re-shows checkbox" scope.

**Tests reviewed and re-run** (`test_auth_api`, `test_auth_service`, `test_sso_service`, `test_sso_api`, `test_guest_upgrade_api` → 29 passed). Coverage is complete against all acceptance criteria: guest reject-without / accept-with consent + stamped version; SSO login reject-without consent; callback persists version + non-null timestamp; stale re-record; idempotent returning user; live-DB `test_upsert_records_and_updates_consent`; frontend checkbox render, disabled-until-checked, and consent-threaded SSO/guest calls.

Out-of-scope changes present in the working tree (BFF cookie transport SEC-04, session-registry SEC-05, SSRF/untrusted-content SEC-01/02) are not part of this review.
