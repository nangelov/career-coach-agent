# Engineer report — SEC-06-consent-gate · Revision 1

## Summary
Consent gate (ToS + privacy acceptance) so **no session is minted without acceptance** (§6.22 / §7.6).
- **SSO login:** consent ticked on the login screen threads `consent=1` → backend `/login` (rejected 400
  before the provider redirect if absent). The accepted policy version is stashed in the Redis OAuth-state
  record and, at callback, recorded against the `users` row as `consent_policy_version` + `consent_accepted_at`.
- **Guest:** `POST /api/auth/guest` now requires `{"consent": true}`; the accepted policy version is stamped
  on the transient Redis session record (guests hold nothing durable, §6.18).
- **Re-prompt on bump:** every login re-records the accepted version, so a stale `consent_policy_version` is
  overwritten on the next login (the checkbox is always re-shown). No mid-session force-logout (documented
  scope boundary).

## Files changed
Backend
- `app/config.py` — new `CONSENT_POLICY_VERSION` (default `"2026-07-13"`); the single source of truth /
  re-consent mechanism.
- `migrations/versions/20260713_0006_consent.py` — new revision `0006` (revises `0005`): adds nullable
  `users.consent_policy_version` + `consent_accepted_at`. Upgrade/downgrade both verified via offline SQL.
- `app/repositories/models/identity.py` — the two consent columns on `User`.
- `app/services/user_store.py` — `UserAccount` carries consent fields; `UserStore.upsert` gains
  `consent_policy_version` / `consent_accepted_at` (default `None` → existing non-login callers unaffected).
- `app/repositories/user_store.py` — writes consent on both insert **and** conflict-update.
- `app/services/oauth_state_store.py` — `OAuthStateRecord.consent_policy_version` (threads consent across the
  two-request OIDC flow).
- `app/schemas/auth.py` — `GuestSessionRequest {consent}`; `SessionRecord.consent_policy_version`.
- `app/services/auth.py` — new `ConsentRequired`; `GuestAuthService.create_guest_session(consent=...)` and
  `SsoAuthService.begin_login(consent=...)` reject without consent; `complete_login` persists consent on upsert.
- `app/api/auth.py` — guest endpoint reads the body, login endpoint reads `consent` query; both map
  `ConsentRequired` → 400.

Frontend
- `lib/auth.ts` — `createGuestSession` sends `{consent:true}`; `beginSsoLogin` gains `consent?` →
  `consent=1` (ordered after `upgrade_ticket`); `upgradeGuestToSso` threads `consent:true`.
- `components/Login.tsx` — consent checkbox with `/terms` + `/privacy` links; all three buttons disabled
  until checked; passes consent through.
- `components/UpgradePrompt.tsx` — fallback `beginSsoLogin` passes `consent:true` (guest already consented).
- `app/api/auth/guest/route.ts` — reads consent from the browser body, forwards `{consent}` to the backend.
- `app/api/auth/login/[provider]/route.ts` — backend 400 → `login_error=consent_required`.

## Key decisions
- **Backend is the real enforcement; UI disabled-button is UX only** (task steps 3/4/6). Consent is checked
  in the *services* (`ConsentRequired`), mapped to 400 in the thin router — keeps Router→Service SoC.
- **Reused `oauth_state_store` to carry consent through the redirect** (task step 3) rather than a second
  mechanism — `users` doesn't exist at `/login`, so the accepted version rides the existing Redis txn.
- **`upsert` consent params default `None`** (columns are nullable) so non-login callers (admin seed / other
  tests) are untouched — avoids a breaking signature change while the SSO flow always passes real values.
- **Re-prompt = re-record on every login** (task step 5): no extra version-compare logic needed; the stored
  version is overwritten each login, naturally satisfying the stale-version criterion.
- **Upgrade flow threads `consent:true`** (guest consented at guest-start): the guest→account SSO path reuses
  `/login`, which now requires consent, so it must carry it or break. Scoped note: a dedicated re-consent UI
  on the upgrade prompt is **not** built here (SEC-06 is Login.tsx only) — the guest's just-accepted consent
  is carried to the new user row.

## How to verify
- Backend: `cd backend && .venv/bin/python -m pytest -q` (unit). Live-DB consent round-trip:
  `make test-integration` (needs the compose Postgres + `alembic upgrade head`).
- Migration: `alembic upgrade 0005:0006 --sql` / `downgrade 0006:0005 --sql` show the two ADD/DROP COLUMNs.
- Frontend: `cd frontend && npx jest && npx tsc --noEmit`.
- Manual: login screen buttons are inert until the checkbox is ticked; `/terms` + `/privacy` links present;
  `POST /api/auth/guest` with no/false consent → 400; `GET /api/auth/login/google` without `consent=1` → 400.

## Tests (final step — mandatory)
- **Backend** `pytest -q`: **477 passed, 54 skipped** (Postgres integration suites skip — no DB reachable in
  this sandbox, same as CI). Added: guest/login/service consent-rejection + accept tests, SSO callback
  persists version+timestamp, stale-version re-record, and a live-DB `test_upsert_records_and_updates_consent`
  (runs when Postgres is up).
- **Backend lint/type**: `ruff check` clean; `mypy app/ migrations/` — Success, 102 files.
- **Migration**: single head `0006`; offline upgrade/downgrade SQL both correct.
- **Frontend** `jest`: **123 passed, 13 suites**; `tsc --noEmit` clean; `eslint` clean on changed files.
- No failing tests. Test updates were required because the session-creation signatures now carry consent;
  each was updated to accept/assert consent (not weakened).

## Self-check
- [x] Meets acceptance criteria (guest reject/accept; SSO reject without consent; callback persists
      version+timestamp; stale re-record; checkbox + disabled buttons + `/terms` `/privacy`; migration
      up/down; tests).
- [x] No secrets committed; Router→Service→Repository layering respected (enforcement in services).
- [x] Tests/lints pass (results above).
