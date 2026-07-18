# Task FIX-12-sso-unconfigured-provider-error — SSO login must fail cleanly when a provider is unconfigured
- **Phase:** cross-cutting   **Status:** ENG   **Tags:** (B)

## Bug report (from human manual testing)
Screenshots in `dev-board/human manual tests/`:
- `Screenshot 2026-07-18 214805.png` — clicking "Sign in with Google" lands on Google's own
  error page: **"Access blocked: Authorisation error" / Error 400: invalid_request / Missing
  required parameter: client_id**.
- `Screenshot 2026-07-18 214832.png` — same error surfaced as a modal ("Error 400:
  invalid_request", `flowName=GeneralOAuthFlow`).

## Root cause (confirmed by reading the code — do not re-diagnose from scratch)
- `backend/app/config.py`: `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `LINKEDIN_CLIENT_ID` /
  `LINKEDIN_CLIENT_SECRET` all default to `""` (intentionally optional, so you can run with only
  one provider configured — do not make them required `Settings` fields).
- `backend/app/services/auth.py::SsoAuthService.begin_login` only calls
  `_require_known_provider` (name is `"google"`/`"linkedin"` → else 404) and checks `consent`.
  It never checks whether that provider's `client_id`/`client_secret` are actually non-empty
  before calling `AuthlibOIDCClient.create_authorization_request`.
- `backend/app/security/oidc.py::AuthlibOIDCClient` happily builds an authorization URL with
  `client_id=""` and the API (`backend/app/api/auth.py::sso_login`) 302-redirects the browser
  straight to Google with that blank `client_id` — which is what produces the screenshotted
  Google error page. The frontend BFF (`frontend/app/api/auth/login/[provider]/route.ts`)
  already has a `provider_unavailable` fallback path (for non-3xx / non-2xx responses from the
  backend) but it never gets used because the backend currently returns a 3xx redirect either way.

## Scope
Make an unconfigured provider fail **inside our own stack** with a clear, recoverable error
instead of round-tripping the browser to the OAuth provider with an invalid request:
1. In `SsoAuthService.begin_login` (`backend/app/services/auth.py`), after
   `_require_known_provider`, check that the resolved provider's `client_id` **and**
   `client_secret` are non-empty. If either is blank, raise a new, clearly-named exception
   (e.g. `ProviderNotConfigured`) — checked *before* `consent` is required is fine either order,
   but must happen before any call into `OIDCClient`/Authlib and before any upgrade ticket is
   consumed.
2. In `backend/app/api/auth.py::sso_login`, catch that exception and return **503 Service
   Unavailable** (not a redirect) with a clear `detail`, alongside the existing
   `UnknownProvider` (404) / `ConsentRequired` (400) handling.
3. The frontend BFF handler (`frontend/app/api/auth/login/[provider]/route.ts`) already treats
   any non-3xx backend response as "login could not start" and redirects to
   `/?login_error=provider_unavailable`; confirm 503 flows through that same branch (it should,
   since the branch is "anything else" → `provider_unavailable`) — add/adjust a test if the
   existing coverage doesn't already assert this.
4. Add a login-screen check: if a provider's login button is rendered but the provider is not
   configured server-side, prefer surfacing the same `provider_unavailable` messaging rather
   than a broken button — **only if** this is a small, low-risk addition; do not build new
   provider-discovery plumbing for this. If it requires a new endpoint or meaningfully larger
   surface, skip this bullet and just make sure the 503 → `provider_unavailable` redirect path
   (bullets 1–3) works end to end; note the deferral in `engineer.md`.

## Acceptance criteria
- [ ] `begin_login` raises a distinct exception when the target provider's `client_id` or
      `client_secret` is empty, and this is unit-tested (both providers, both fields).
- [ ] `GET /api/auth/login/{provider}` returns `503` (not a redirect) for an unconfigured
      provider, tested via the existing FastAPI test client style used in
      `backend/tests/test_sso_api.py` / `test_sso_service.py`.
- [ ] `UnknownProvider` (unknown name → 404) and `ConsentRequired` (no consent → 400) behavior is
      unchanged.
- [ ] Frontend `login/[provider]/route.ts` behavior for a non-2xx/3xx backend response is
      covered (existing test in `frontend/__tests__/bffAuthRoutes.test.ts` or equivalent) —
      extend if it doesn't already assert the 503 case.
- [ ] No secrets committed; `.env` / `.env.example` untouched unless documentation-only.
- [ ] Backend + frontend test suites pass.

## Design references
- dev-board/tasks.md — P3 "Auth, sessions & guest mode" (P3-02 SSO via Authlib OIDC — already
  `[x]`; this is a bug fix on top of it, not a new feature).
- dev-board/app-design-and-features.md — §7.1 (OIDC login flow), §7.2 / §6.13 (BFF handles the
  provider redirect).

## Constraints / non-goals
- Do not make `GOOGLE_CLIENT_ID`/`LINKEDIN_CLIENT_ID`/secrets required `Settings` fields —
  running with only one provider configured must keep working.
- Do not add new provider credentials or attempt to fix any specific developer's local `.env` —
  this is a code-robustness fix, not a credentials-provisioning task.
- Do not touch the OAuth flow itself (PKCE, state, token exchange) — only add the pre-flight
  "is this provider configured" guard.
