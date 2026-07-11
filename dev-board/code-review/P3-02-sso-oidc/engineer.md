# Engineer report — P3-02-sso-oidc · Revision 1

## Summary
Implemented backend-owned SSO via OIDC (Google + LinkedIn) with PKCE, plus the reusable
session-verify dependency and logout, all on top of the P3-01 session/token foundation so
guest and logged-in flows issue a **byte-compatible bearer token** the frontend treats
uniformly (`SessionResponse` mirrors `GuestSessionResponse` field-for-field; both decode via
the same `SessionTokenCodec`).

Flow: `GET /api/auth/login/{provider}` builds a PKCE authorization request (minimal scopes
`openid email profile`) and stashes the pending transaction in Redis, then 302-redirects to
the provider. The provider redirects back to `GET /api/auth/callback/{provider}`, which
verifies `state`, exchanges the code (PKCE verifier), upserts the `users` row (no password
ever stored), mints a short-lived `role="user"` session JWT, and 302-redirects to the
frontend with the token in the URL **fragment**. `require_auth` verifies the JWT + a live
session record; `POST /api/auth/logout` deletes the record (immediate revocation, no
denylist).

Layering respected: Router (`api/auth.py`, thin — HTTP/redirect/error-mapping only) →
Service (`services/auth.py`: `SsoAuthService`, `SessionAuthenticator`) → ports
(`OIDCClient`, `OAuthStateStore`, `UserStore`, `SessionStore`, `SessionTokenCodec`) with
concrete adapters in `repositories/` + `security/`. No live network / provider credentials
needed to test (Authlib driven through an injected `httpx.MockTransport`; service/API tests
use fakes + in-memory stores).

## Files changed
New:
- `app/security/oidc.py` — `OIDCClient` port + `AuthlibOIDCClient` (PKCE S256 authorization
  URL, code exchange, userinfo-based identity resolution); `OIDCUserInfo`,
  `AuthorizationRequest`, `ProviderConfig`, `OIDCError`. Injectable httpx `transport` seam.
- `app/security/dependencies.py` — `require_auth` FastAPI dependency (→ `CurrentUser`) +
  `get_session_authenticator`. Lives below `api/` so any router reuses it without coupling.
- `app/services/oauth_state_store.py` — `OAuthStateStore` port + `OAuthStateRecord` +
  `InMemoryOAuthStateStore` (pending PKCE transaction spanning login↔callback).
- `app/services/user_store.py` — `UserStore` port + `UserAccount` + `InMemoryUserStore`.
- `app/repositories/user_store.py` — `PostgresUserStore` (upsert on `uq_users_provider_sub`).
- `docs/oauth-setup.md` — copy-paste manual OAuth-app registration checklist (Google +
  LinkedIn), redirect-URI table, scopes, secret placement, verify steps.
- Tests: `test_oidc_client.py`, `test_oauth_state_store.py`, `test_user_store.py`,
  `test_sso_service.py`, `test_session_authenticator.py`, `test_sso_api.py`,
  `test_user_store_postgres.py` (live-DB, auto-skips).

Modified:
- `app/services/auth.py` — added `SsoAuthService` (`begin_login`/`complete_login`),
  `SessionAuthenticator` (`authenticate`/`end_session`), `UnknownProvider`,
  `InvalidOAuthState`.
- `app/api/auth.py` — added `GET /login/{provider}`, `GET /callback/{provider}`,
  `POST /logout`, and the `get_sso_auth_service` dependency.
- `app/schemas/auth.py` — added `SessionResponse` (logged-in token, same shape as guest) and
  `CurrentUser`.
- `app/services/session_store.py` — added `delete` to the `SessionStore` port + InMemory
  (needed for logout/revocation).
- `app/repositories/redis.py` — `RedisSessionStore.delete`; new `RedisOAuthStateStore`
  (prefix `oauth:state`, single-use `pop`).
- `app/bootstrap.py` — `build_sso_auth_service`, `build_session_authenticator`.
- `app/app_state.py` — `SSO_AUTH_SERVICE`, `SESSION_AUTHENTICATOR` keys.
- `app/config.py` — `OAUTH_REDIRECT_BASE_URL`, `OAUTH_POST_LOGIN_REDIRECT`,
  `OAUTH_METADATA_URLS`, `OAUTH_SCOPES`, `OAUTH_STATE_TTL_SECONDS`, `USER_SESSION_TTL_SECONDS`.
- `tests/fakes.py` — `FakeOIDCClient`.
- `.env.example` — SSO redirect-base + post-login vars, pointer to docs.

## Key decisions
- **OAuth transaction in Redis, not a signed cookie (§7.1, §6.2).** The v2 model is
  Bearer-token-only (Next.js is a pure client); there is no cookie session, and
  `SessionMiddleware`/`itsdangerous` isn't a dependency. A short-lived, single-use Redis
  record (`OAuthStateStore`, `pop` = get-then-delete) carries the PKCE verifier + nonce
  between login and callback and doubles as CSRF (callback `state` must match one we issued).
- **PKCE S256 + minimal scopes (§7.1).** `AuthlibOIDCClient` sets
  `code_challenge_method="S256"` and passes a per-attempt `code_verifier`; scopes are exactly
  `openid email profile`. So a leaked client id alone cannot complete a flow.
- **Identity via the userinfo endpoint, not id_token/JWKS.** The just-issued access token
  fetches provider-verified claims over TLS — authoritative — which keeps the implementation
  JWKS-free while PKCE + `state` cover code-interception/CSRF. Documented as a deliberate
  simplification.
- **Logout = delete session record; `require_auth` requires a live record.** Gives immediate
  revocation without a JWT denylist (the accepted tradeoff: one store read per request +
  short JWT TTL as the backstop, §7.1 "short-lived session JWTs"). Works for guest and user
  tokens alike (guest logout is supported).
- **Uniform token shape (compat with P3-01).** `complete_login` mints `sub=users.id`,
  `role="user"`, `sid=session_id` via the same `SessionTokenCodec`; `SessionResponse` mirrors
  `GuestSessionResponse`. Frontend stores/sends one shape for both.
- **Redirect URI derived from config, never hard-coded (acceptance #5).**
  `OAUTH_REDIRECT_BASE_URL` + `/api/auth/callback/{provider}`; the supported-provider set is
  the keys of `OAUTH_METADATA_URLS`. Token delivered to the SPA in the redirect **fragment**
  (not a query param) to avoid server-log/Referer leakage.
- **Postgres upsert via `ON CONFLICT (provider, sub) DO UPDATE ... RETURNING id`** — one
  round-trip, no SELECT-then-branch race; only SSO-provided fields written (no credential
  column, §7.1). Error mapping: unknown provider→404, bad/expired/replayed state→400,
  provider failure→502, missing/invalid token→401.

## How to verify
- `cd backend && .venv/bin/python -m pytest tests/test_sso_api.py tests/test_sso_service.py tests/test_oidc_client.py tests/test_session_authenticator.py tests/test_oauth_state_store.py tests/test_user_store.py -q`
- Manual (with real OAuth apps per `docs/oauth-setup.md`): open
  `<OAUTH_REDIRECT_BASE_URL>/api/auth/login/google` → consent screen URL contains
  `code_challenge` + `state`; after consent you land on `OAUTH_POST_LOGIN_REDIRECT` with
  `#access_token=...`; send it as `Authorization: Bearer` and `POST /api/auth/logout` ends it.

## Tests (final step — mandatory)
- `.venv/bin/ruff check app tests` → All checks passed. `ruff format --check` → all formatted.
- `.venv/bin/mypy app tests` → only the **2 pre-existing** errors remain
  (`tests/test_llm_router.py:309` unused-ignore, `tests/test_message_id.py:71` FakeRegistry
  arg-type) — both in files I did not touch (confirmed present at HEAD in the P3-01 report).
  All new/changed files type-clean under `--strict`.
- `.venv/bin/python -m pytest -q` → **154 passed, 41 skipped** (skips = live-DB integration
  suites, expected without a reachable Postgres; the new `test_user_store_postgres.py` is one
  of them and auto-skips). New P3-02 tests: **30 passed** (29 unit/API + 1 skipped live-DB).
- No test failures. No test weakened/deleted.

## Self-check
- [x] Meets acceptance criteria: login 302→consent (PKCE + minimal scopes); callback exchanges
  code, verifies state/PKCE, upserts `users` (no password), mints JWT; short-lived JWT from a
  Space-secret key + reusable `require_auth`; `POST /logout` ends the session; redirect URIs
  config-derived; tests cover mint/verify/expiry + callback flow against mocked providers with
  no real credentials; `docs/oauth-setup.md` documents manual registration.
- [x] No secrets committed (client secrets + `JWT_SECRET_KEY` env/Space-secret only;
  `.env.example` placeholders). Router→Service→Repository layering; interfaces before
  implementations (`OIDCClient`/`OAuthStateStore`/`UserStore`/`SessionStore` ports before
  adapters).
- [x] Tests/lints pass (see above); pre-existing mypy noise called out, not introduced.
