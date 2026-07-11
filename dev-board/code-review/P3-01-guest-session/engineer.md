# Engineer report — P3-01-guest-session · Revision 1

## Summary
Implemented `POST /api/auth/guest` — starts an anonymous, Redis-only guest session and
returns a backend-signed session JWT (`role=guest`) plus the `session_id` the client keys
subsequent chat/rate-limit calls on. No auth required; no Postgres writes. The token codec
and session-record store are built **generic** so P3-02 (SSO) issues a byte-compatible
bearer token and reuses the same store for logged-in sessions.

Layering respected end-to-end: Router (`api/auth.py`, thin) → Service (`services/auth.py`)
→ ports (`SessionStore`, `SessionTokenCodec`) with the Redis adapter in `repositories/`.

## Files changed
- `app/schemas/auth.py` (new) — `SessionRole` literal (single home), `SessionRecord` (stored
  session doc, generic over guest/user), `GuestSessionResponse` (endpoint body).
- `app/security/__init__.py`, `app/security/tokens.py` (new) — `SessionTokenCodec` (joserfc
  HS256 encode/decode), `SessionClaims`, `InvalidSessionToken`. The one place session JWTs are
  minted/verified; shared by guest + SSO (P3-02's verify dependency).
- `app/services/session_store.py` (new) — `SessionStore` ABC port + `InMemorySessionStore`
  (test double / interim), same interface-before-implementation idiom as SessionMemory.
- `app/services/auth.py` (new) — `GuestAuthService`: mint session id, persist Redis record,
  sign the guest JWT.
- `app/repositories/redis.py` — `StoreRedis` Protocol + `RedisSessionStore` adapter (key
  prefix `session:record`, TTL per create).
- `app/api/auth.py` (new) — `POST /api/auth/guest` router + cached `get_guest_auth_service`
  dependency.
- `app/bootstrap.py` — `build_guest_auth_service`; extracted `_shared_redis_client(app)` so
  chat + auth reuse **one** Redis pool provider (fixes a latent double-pool if auth built
  the provider independently).
- `app/app_state.py` — `AUTH_SERVICE` state key.
- `app/main.py` — include the auth router.
- `app/config.py` — `GUEST_SESSION_TTL_SECONDS` (default 24h) for the Redis record TTL.
- Tests (new): `tests/test_session_token.py`, `tests/test_session_store.py`,
  `tests/test_auth_service.py`, `tests/test_auth_api.py`.

## Key decisions
- **joserfc for JWT, not `authlib.jose`** (§6.2/§7.1 "backend-owned session JWT"). authlib's
  `jose` module is deprecated in favor of joserfc (already installed via authlib). Codec is a
  datastore/framework-free primitive in `app/security/tokens.py` — not `services/` — so both
  auth entry points and P3-02's verify dependency share one shape and one signing path.
- **Uniform token shape for guest + user** (acceptance #2): claims `sub`/`role`/`sid`/`iat`/
  `exp` with `role ∈ {guest,user}`. Guest `sub == sid == session_id` (a guest has no user
  identity, so the session *is* the subject); P3-02 sets `sub=users.id`, `role=user`. Frontend
  treats both uniformly.
- **Generic `SessionStore`/`SessionRecord`, not guest-only** — P3-02 reuses them for logged-in
  sessions (role=user, user_id set) instead of a second type (DRY/YAGNI-balanced).
- **Redis-only for guests** (acceptance #3, §4): `build_guest_auth_service` wires no Postgres;
  the `GuestAuthService` never touches the conversation store.
- **`session_id` = `uuid4().hex`** (32 chars) — within the 64-char `sessions.id` /
  `ChatRequest.session_id` bound, and usable directly as the P3-04 rate-limit key (acceptance
  #4).
- **Two TTLs, deliberately** (acceptance #1): the bearer JWT is short-lived
  (`JWT_EXPIRE_MINUTES`, §7.1 "short-lived session JWTs") while the Redis session record lives
  `GUEST_SESSION_TTL_SECONDS` (24h, ≥ token lifetime) so the session + rate-limit state
  survives a token refresh. Both are TTL'd. Documented on the config field.
- **Decode implemented now** (not just encode) so the token contract is round-trip-verified in
  tests and P3-02 inherits a ready verify primitive; `InvalidSessionToken` hides joserfc error
  types from callers (→ 401 in P3-02).

## How to verify
- `cd backend && .venv/bin/python -m pytest tests/test_auth_api.py tests/test_auth_service.py tests/test_session_store.py tests/test_session_token.py -q`
- End-to-end (no DB/Redis needed, thanks to the dependency override in the API test): the
  endpoint returns 201 with `{access_token, token_type:"bearer", session_id, role:"guest",
  expires_in}`, persists a guest `SessionRecord`, and the token decodes to `role=guest` with
  `sid == session_id`.

## Tests (final step — mandatory)
- `.venv/bin/ruff check app tests` → All checks passed. `ruff format --check` → clean.
- `.venv/bin/mypy app tests` → only **2 pre-existing** errors remain
  (`tests/test_llm_router.py:309` unused-ignore, `tests/test_message_id.py:71` FakeRegistry
  arg-type) — confirmed present at clean HEAD via `git stash -u`; both are in files I did not
  touch and are out of scope. All my new/changed files type-clean under `--strict`.
- `.venv/bin/python -m pytest -q` → **125 passed, 40 skipped** (skips are the live-DB
  integration suites, expected without a real Postgres). New auth tests: **23 passed**.

## Self-check
- [x] Meets acceptance criteria (Redis record + TTL; uniform bearer token distinguishing
  role=guest; no Postgres writes; session_id as rate-limit key; no auth to call; tests for
  creation/TTL/shape).
- [x] No secrets committed; signing key sourced only from `JWT_SECRET_KEY` (env/Space Secret).
  Router→Service→Repository layering respected; interfaces before implementations.
- [x] Tests/lints pass (see above); pre-existing mypy noise called out, not introduced.
