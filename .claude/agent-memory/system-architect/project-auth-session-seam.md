---
name: project-auth-session-seam
description: Blessed P3-01 guest-session/auth seam — security/ pkg for token codec, generic SessionStore/SessionRecord, uniform guest+user JWT shape, joserfc ruling; for P3-02+
metadata:
  type: project
---

Blessed P3-01 (guest session endpoint `POST /api/auth/guest`, APPROVED rev 1).

**Blessed patterns (hold P3-02..P3-07 to these):**
- **`app/security/` is an accepted §8 extension** — a framework/datastore-free auth-primitives
  package (currently `tokens.py` = `SessionTokenCodec` HS256 encode/decode, `SessionClaims`,
  `InvalidSessionToken`). Keeps `api/auth.py` thin and `services/auth.py` free of JWT crypto.
  P3-02 OIDC/PKCE state + the FastAPI verify dependency belong in `security/` or the thin router,
  NOT smeared into `services/`. Do not re-litigate the module's existence.
- **One session JWT shape for guest AND user** (§7.1/§9): claims `sub/role/sid/iat/exp`,
  `role ∈ {guest,user}` (`SessionRole` literal lives once in `schemas/auth.py`). Guest:
  `sub==sid==session_id`; user (P3-02): `sub=users.id`, `role=user`. Frontend treats both
  uniformly. `exp` is essential-validated (short-lived, §7.1). Signing key only from
  `JWT_SECRET_KEY`; empty secret fails at codec construction.
- **Generic `SessionStore` ABC + `SessionRecord`** (`services/session_store.py` port,
  `RedisSessionStore` adapter in `repositories/redis.py`, key prefix `session:record`). Reused for
  logged-in sessions in P3-02 (set `user_id`), not a second type. Guests are **Redis-only, no
  Postgres** (§4) — `build_guest_auth_service` wires no PG.
- **joserfc, not `authlib.jose`, for JWT minting is fine** — design mandates Authlib for the OIDC
  *flow* (P3-02), not for JWT; `authlib.jose` is deprecated, authlib pins `joserfc>=1.6.0`. Minor
  follow-up (non-gating): declare joserfc as a direct pyproject dep.
- **Single shared Redis pool reused across composition entry points** — `bootstrap._shared_redis_client(app)`
  is the one path; chat + auth share the one `RedisConnectionProvider` on `app.state`. A second
  pool/wiring path is a finding (extends [[cr01-audit-rulings]] single-composition-root ruling).

**Blessed P3-02 (SSO OIDC login/callback/logout, APPROVED rev 1) — hold P3-03+ to these:**
- **`security/oidc.py` = OAuth mechanics behind `OIDCClient` port** (AuthlibOIDCClient, PKCE S256,
  injectable httpx transport); `security/dependencies.py` = reusable `require_auth`→`CurrentUser`.
  OAuth-state + user-store **ports live in `services/`**, adapters in `repositories/`
  (`RedisOAuthStateStore`, `PostgresUserStore` upsert on `uq_users_provider_sub`). Do not re-litigate.
- **Logged-in `sessions` are Redis-anchored, NOT the §4 Postgres table** — this is the accepted
  documented decision (was the open follow-up). Session record = revocation handle in
  `RedisSessionStore` (TTL `USER_SESSION_TTL_SECONDS`); durable identity in Postgres `users`. Port
  makes a later PG `sessions` adapter cheap. Don't flag Redis user-sessions as a §4 violation.
- **Identity via `userinfo` endpoint, not `id_token`/JWKS** — accepted simplification (PKCE+state
  cover CSRF/interception). Consequence: generated `nonce` is stored but unverified → a code-review
  concern, NOT an architecture gate.
- **Logout = delete Redis session record; `require_auth` requires a live record** — immediate
  revocation without a JWT denylist; one store read/request + short JWT TTL is the accepted tradeoff.

**Open follow-up carried to P3-04 (authz/verify):**
- CR-01 **A10 still open**: remove client-trusted `ChatRequest.user_id`; populate identity from the
  verified token via the new `require_auth`/`CurrentUser` seam (see [[conversation-persistence]]).
