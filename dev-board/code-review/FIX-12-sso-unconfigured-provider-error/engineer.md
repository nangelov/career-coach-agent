# Engineer report — FIX-12-sso-unconfigured-provider-error · Revision 1

## Summary
An unconfigured SSO provider (blank `client_id`/`client_secret`) now fails **inside our own
stack** instead of 302-redirecting the browser to Google/LinkedIn with a blank `client_id`
(which surfaced as the provider's "Error 400: invalid_request / Missing required parameter:
client_id" page in manual testing). `SsoAuthService.begin_login` runs a pre-flight credential
check before any OIDC call or upgrade-ticket consumption; the API maps the resulting exception
to **503**; the frontend BFF already routes any non-3xx to `?login_error=provider_unavailable`;
and the login screen now actually surfaces that reason (the `login_error` param was previously
dead — nothing read it).

Note: the repo already had an uncommitted partial start (the `ProviderNotConfigured` class,
the `provider_credentials` constructor param + attribute) that left `from_settings` and every
direct `SsoAuthService(...)` test construction broken (missing required arg). This revision
completes and wires it through end to end.

## Files changed
- `backend/app/services/auth.py` — added `_require_configured_provider` (both `client_id` and
  `client_secret` must be non-empty) called first in `begin_login`, before consent/OIDC/ticket;
  wired `provider_credentials` into `SsoAuthService.from_settings` from the config credential
  fields. (`ProviderNotConfigured` + the ctor param already existed from the partial start.)
- `backend/app/api/auth.py` — `sso_login` now catches `ProviderNotConfigured` → **503** (before
  the redirect), alongside the existing `UnknownProvider` 404 / `ConsentRequired` 400 / `OIDCError`
  502; docstring updated.
- `backend/tests/test_sso_service.py` — added `provider_credentials` to the `_service` helper
  (defaults to both configured); parametrized unit tests covering both providers × both blank
  fields (and both-blank), asserting no OIDC call and no persisted PKCE transaction on failure;
  plus a "one provider configured, the other not" test.
- `backend/tests/test_sso_api.py` — factored the fixture's service build into `_build_sso`; added
  `test_login_unconfigured_provider_503` (unconfigured google → 503, configured linkedin → 302).
- `backend/tests/test_p3_exit_verification.py`, `backend/tests/test_guest_upgrade_api.py` —
  pass `provider_credentials` to their direct `SsoAuthService(...)` constructions (were broken by
  the new required kwarg).
- `frontend/__tests__/bffAuthRoutes.test.ts` — added an explicit 503 → `provider_unavailable`
  case for the login BFF handler.
- `frontend/components/Chat.tsx` — on mount, read `?login_error=<reason>`, map it to a friendly
  banner via the existing `loginMessage`/`Login message` prop, then strip the param
  (`history.replaceState`) so a refresh is clean. Completes bullet 4 without new plumbing.

## Key decisions
- **Credential check lives in the service, keyed off injected `provider_credentials`** (not by
  reaching into the OIDC client): keeps the pre-flight off the network and Router→Service→Repo
  layering intact. Order in `begin_login`: known-provider (404) → configured (503) → consent (400)
  → ticket → OIDC. Task allowed either 503/400 order; configured-before-consent means an
  unconfigured provider never consumes an upgrade ticket. (task §Scope 1; §7.1)
- **`GOOGLE_*`/`LINKEDIN_*` stay optional `Settings` fields** — running with only one provider
  provisioned keeps working (verified by test). No config schema change. (constraints/non-goals)
- **503 (not 502)** for unconfigured: distinct from `OIDCError`'s 502 (provider-reachability),
  and it flows through the BFF's existing "anything else → provider_unavailable" branch. (Scope 2/3)
- **Bullet 4 done as a small addition, not deferred**: the `login_error` query param was already
  emitted by the BFF but never surfaced anywhere. Reading it in the existing client `Chat` mount
  effect and feeding the existing `Login message` prop is low-risk and needs no new endpoint /
  provider-discovery. (Scope 4)

## How to verify
- Backend: `cd backend && <LIVE_DB_ENV> .venv/bin/python -m pytest tests/test_sso_service.py
  tests/test_sso_api.py -q` (or the full suite).
- Frontend: `cd frontend && npx jest bffAuthRoutes Chat`.
- Manual: with `GOOGLE_CLIENT_ID=""`, `GET /api/auth/login/google?consent=1` → 503 (not a 302 to
  Google); the browser lands back on `/?login_error=provider_unavailable` with a banner.

## Tests (final step — mandatory)
- Backend full suite: `pytest` (live DB env sourced from root `.env`) → **747 passed, 62 skipped**.
- Backend focused SSO: **25 passed**. `mypy app/services/auth.py app/api/auth.py` → clean;
  `ruff check` (changed files) → clean.
- Frontend full suite: `npx jest` → **192 passed, 20 suites**. `tsc --noEmit` → clean;
  `eslint` (changed files) → clean.
- One failure surfaced mid-run and was fixed at root cause: the new required `provider_credentials`
  kwarg broke direct `SsoAuthService(...)` constructions in `test_p3_exit_verification.py` and
  `test_guest_upgrade_api.py` (10 errors) — updated both to pass configured credentials (the tests
  asserted stale constructor shape). Re-ran to green.

## Self-check
- [x] Meets acceptance criteria (distinct exception unit-tested both providers/both fields;
      503 via test client; 404/400 unchanged; BFF 503 case covered; `.env`/`.env.example` untouched;
      both suites pass)
- [x] No secrets committed; Router→Service→Repo layering respected (check is in the service off
      injected credentials; API only maps to HTTP)
- [x] Tests/lints pass (results pasted above)
