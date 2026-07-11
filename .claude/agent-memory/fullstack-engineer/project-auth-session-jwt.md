---
name: project-auth-session-jwt
description: v2 session-JWT + guest-session conventions — joserfc (not authlib.jose), codec in app/security/, generic SessionStore/SessionRecord port
metadata:
  type: project
---

Established in P3-01 (guest session endpoint); P3-02 (SSO) + P3-04 (rate limits) build on it.

**JWT codec = joserfc, not `authlib.jose`.** `authlib.jose` is deprecated (emits
`AuthlibDeprecationWarning`, "use joserfc instead"). `joserfc` ships with authlib and is the
installed backend. API: `from joserfc import jwt; jwt.encode({'alg':'HS256'}, claims, OctKey.import_key(secret))`
returns a **str**; `jwt.decode(token, key, algorithms=[alg]).claims`; validate exp via
`JWTClaimsRegistry(exp={'essential':True}).validate(claims)`. Errors subclass `joserfc.errors.JoseError`.

**The backend session-JWT codec lives in `app/security/tokens.py`** (`SessionTokenCodec`), a
datastore/framework-free primitive — NOT in `services/`. It is the one place tokens are
minted/verified, shared by guest + SSO. Contract: claims `sub`/`role`/`sid`/`iat`/`exp`;
`role` is `SessionRole = Literal["guest","user"]` (single home in `app/schemas/auth.py`).
`InvalidSessionToken` wraps all joserfc/validation errors so callers never import joserfc
error types (P3-02's verify dependency maps it to 401). §8 doesn't list `security/`; it's the
natural home and reviewers accepted the SoC boundary.

**Session records use a generic port, not a guest-only one.** `SessionStore`
(`services/session_store.py`, ABC + `InMemorySessionStore`) + `RedisSessionStore`
(`repositories/redis.py`, key prefix `session:record`) + `SessionRecord`
(`schemas/auth.py`: session_id/role/user_id/created_at). Built generic so P3-02 reuses it
for logged-in sessions (role="user", user_id set) instead of a second type. Follows the
SessionMemory/CancelRegistry port-in-services + adapter-in-repositories idiom.

**Shared Redis pool across composition entry points:** `bootstrap._shared_redis_client(app)`
reuses the `RedisConnectionProvider` stashed on `app.state` (builds once) so chat + auth +
future builders share ONE bounded pool — the second builder must not create a second pool.
See [[project-composition-root]].

**P3-02 SSO OIDC (added):**
- **OAuth transaction is Redis-backed, NOT a cookie.** No `SessionMiddleware`/`itsdangerous`
  (not installed; conflicts with the Bearer-only model). Port `OAuthStateStore`
  (`services/oauth_state_store.py`, `OAuthStateRecord` = provider/code_verifier/nonce/
  redirect_uri/created_at) + `RedisOAuthStateStore` (`repositories/redis.py`, prefix
  `oauth:state`, `pop` = get-then-delete = single-use anti-replay). State keys the txn AND is
  the CSRF token.
- **OIDC client is a port in `app/security/oidc.py`** (`OIDCClient` base + `AuthlibOIDCClient`
  over `authlib.integrations.httpx_client.AsyncOAuth2Client`). PKCE S256 (pass
  `code_challenge_method="S256"` on client + `code_verifier=` to `create_authorization_url`).
  Identity resolved via the **userinfo endpoint** (not id_token/JWKS) — provider-verified over
  TLS, keeps it JWKS-free. Inject `transport=httpx.MockTransport` for tests (no network); route
  discovery/token/userinfo by path. `ProviderConfig` is public so tests build the client.
- **User upsert:** `UserStore` port (`services/user_store.py`, `UserAccount`) + `PostgresUserStore`
  (`repositories/user_store.py`) — `pg_insert(...).on_conflict_do_update(constraint="uq_users_provider_sub").returning(User.id)`. `UserAccount.id = str(user.id)` becomes JWT `sub`.
- **Reusable auth dep:** `require_auth` in `app/security/dependencies.py` (below `api/`, so any
  router imports it without router→router coupling) → `CurrentUser` (schemas/auth.py). Backed by
  `SessionAuthenticator` (in `services/auth.py`): decode JWT AND check the session record still
  exists — so `POST /logout` (deletes record) = immediate revocation, no denylist (accepted
  tradeoff = 1 store read/request + short JWT TTL). `HTTPBearer(auto_error=False)` → uniform 401.
- **Callback delivers the token in the redirect URL fragment** (`#access_token=...` to
  `OAUTH_POST_LOGIN_REDIRECT`), never a query param (server-log/Referer leak). Login=302 to
  consent; unknown provider=404, bad/expired state=400, provider error=502.
- **Redirect URI derived from config** (`OAUTH_REDIRECT_BASE_URL` + `/api/auth/callback/{provider}`),
  never hard-coded. Providers set = keys of `OAUTH_METADATA_URLS` (google/linkedin discovery URLs
  are public constants, safe as config defaults). Manual OAuth-app steps in `docs/oauth-setup.md`.
