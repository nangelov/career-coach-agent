# Engineer report — P3-04-authz-ratelimits · Revision 1

## Summary
Implemented (1) **own-data-only AuthZ** and (2) **Redis-backed rate limiting** on the
user-scoped endpoints that exist so far (chat + cancel), keyed off the identity established at
login in P3-01/P3-02.

- **AuthZ.** `POST /api/chat` and `POST /api/chat/{session}/cancel` now require a valid bearer
  token (`require_auth`) and enforce a single, centralized own-data check
  (`authorize_session_access`): a caller may only act on **their own** session (the token's
  `sid`), else `403`. Critically, the turn's `user_id` is now taken from the **verified token**
  (`CurrentUser.user_id`), never from the request body — the client-controlled `user_id` field
  (an authZ hole and a P2 interim stand-in) was removed from `ChatRequest`. This closes the P1
  gap noted in-code ("anyone who knows a session_id can cancel it") and the P2 note that the
  request-body `user_id` "is not an authorization boundary."
- **Rate limits.** A new `RateLimitService` (policy) over a `RateLimiter` port with a
  Redis fixed-window counter (`RedisRateLimiter`, `INCR` + first-hit `EXPIRE`). Guests are
  capped at **10 messages + 1 document upload per session** (Decision 8), keyed on the guest
  `session_id`; logged-in users get a separate, far more generous per-window limit
  (**120 messages/hour + 20 uploads/hour** by default, documented/configurable), keyed on
  `users.id`. The chat endpoint enforces the message limit before opening the stream, returning
  `429` with an upgrade-prompting message + `Retry-After` when a guest is over budget. The
  upload action is a first-class part of the policy/port (proven at the service boundary) ready
  for the P5 CV-upload route to call with one line.

Layering respected end-to-end: Router (`api/chat.py`, thin) → Service
(`services/rate_limiting.py` policy) → port (`RateLimiter`) with the Redis adapter in
`repositories/redis.py`; the authZ/authN/rate-limit *dependencies* live in `security/` (below
`api/`), wired at the composition root (`bootstrap.py`).

## Files changed
New:
- `app/services/rate_limiting.py` — `RateLimitAction` (message/upload), `RateLimitResult`,
  `RateLimitExceeded`, the `RateLimiter` ABC **port** + `InMemoryRateLimiter` test double, and
  `RateLimitService` (the guest-vs-user policy: resolves key/limit/window, enforces, raises).
- `tests/test_rate_limiting.py` — policy + Redis-adapter unit tests (guest 10th ok/11th denied;
  upload 1 ok/2nd denied; budgets independent; sessions isolated; user tier generous + keyed on
  user_id; fixed-window `EXPIRE`-once + retry-after).
- `tests/test_authz_ratelimit_api.py` — API-boundary tests (cross-session `403`; guest 11th
  message `429` with upgrade prompt + `Retry-After`; a `403` doesn't consume budget).

Modified:
- `app/api/chat.py` — chat + cancel now depend on `require_auth`; call
  `authorize_session_access` (authz **before** rate-limit); chat enforces the message limit and
  maps `RateLimitExceeded`→`429`; `user_id` now sourced from `current_user`, not the body.
- `app/schemas/chat.py` — **removed** the client-controlled `user_id` field from `ChatRequest`
  (identity now comes from the token); updated the docstring to state the authZ contract.
- `app/security/dependencies.py` — added `authorize_session_access` (403 own-data check),
  `get_rate_limit_service` dependency, and `rate_limit_exceeded_http` (429 mapper + Retry-After).
- `app/repositories/redis.py` — `LimiterRedis` Protocol seam + `RedisRateLimiter` fixed-window
  counter (reuses the shared pool).
- `app/bootstrap.py` — `build_rate_limit_service` (Redis-only, over the shared pool).
- `app/app_state.py` — `RATE_LIMIT_SERVICE` state key.
- `app/config.py` — `GUEST_RATE_LIMIT_WINDOW_SECONDS`, `USER_MAX_MESSAGES_PER_WINDOW` (120),
  `USER_MAX_UPLOADS_PER_WINDOW` (20), `USER_RATE_LIMIT_WINDOW_SECONDS` (3600); expanded the
  guest-cap field docs to cite Decision 8.
- `tests/fakes.py` — `fake_current_user(...)` + `unlimited_rate_limit_service()` shared helpers
  for overriding `require_auth` / `get_rate_limit_service` in API tests.
- `tests/test_chat_api.py`, `tests/test_chat_cancel.py`, `tests/test_p2_exit_verification.py` —
  updated to authenticate (the chat/cancel routes now require a token); added
  `requires_auth`/cross-session-`403` cases.

## Key decisions
- **Identity from the token, `user_id` field removed (§7 AuthZ).** The P2 `ChatRequest.user_id`
  was explicitly documented as an interim stand-in "not an authorization boundary" that P3 would
  replace with the JWT-derived identity. Trusting it would let any caller act as any user, so I
  removed it and derive `user_id=current_user.user_id`. This is *the* P3 change that makes chat
  own-data-safe.
- **Centralized own-data check, not per-route duplication (task requirement).**
  `authorize_session_access(session_id, current_user)` is one helper in `security/`, reused by
  chat + cancel and ready for every future session-scoped route. The session `sid` in the token
  *is* the caller's identity boundary, so "session_id must equal the token's sid" is the whole
  rule — no repository-level query needed for the endpoints that exist today (a repo-scoping
  framework would be YAGNI until profile/dashboard rows land in P5+).
- **AuthZ before rate-limit.** The chat handler runs the `403` check *before* counting the
  message, so a rejected cross-session request never consumes the caller's budget (covered by a
  test).
- **Fixed-window counter, `EXPIRE` only on the first hit.** Keeps the user window *fixed* (a
  continuously-active user still resets each hour) rather than sliding (which would trap them
  once maxed). Guest window = the guest-session lifetime, so the 10/1 caps are per-session and
  the counters self-clean with the session. `INCR`+`EXPIRE` are two commands (tiny crash window
  where a key could miss its TTL) — noted in-code; a Lua/pipeline atomic variant is a future
  hardening (KISS for now).
- **Guest keyed on `session_id`, user keyed on `user_id`.** A guest can't reset its budget by
  minting a new client id (its session *is* its identity); a user's limit follows them across
  sessions. `user_id` falls back to `session_id` defensively so a malformed token never keys on
  an empty subject.
- **Generous user defaults documented (task: "document the number chosen").** 120 messages/hour
  and 20 uploads/hour — abuse guard without throttling normal use; all limits/windows are config
  fields with rationale in their descriptions.
- **Upload limit enforced at the service boundary, not a new route.** No upload endpoint exists
  yet (P5). The upload action is a first-class `RateLimitAction` the policy enforces, tested at
  the service boundary (1 ok / 2nd denied) so P5's route wires it in one call — building an
  upload route now would be out of scope.

## How to verify
- Unit: `cd backend && .venv/bin/python -m pytest tests/test_rate_limiting.py tests/test_authz_ratelimit_api.py -q`
- Own-data: a caller with session `mine` posting `{"session_id":"other",...}` to `/api/chat`
  (or cancelling `other`) gets `403`; no token → `401`.
- Guest cap: 10 `POST /api/chat` on one guest session return `200`; the 11th returns `429` with
  detail containing "Sign in" and a `Retry-After` header.
- User tier: a logged-in caller is limited far more generously and the counter follows the
  `user_id` across sessions (unit test).

## Tests (final step — mandatory)
- `.venv/bin/ruff check app tests` → All checks passed. `ruff format` → clean (new files
  auto-formatted during authoring).
- `.venv/bin/mypy app tests` → only the **2 pre-existing** errors remain
  (`tests/test_llm_router.py:309` unused-ignore, `tests/test_message_id.py:71` FakeRegistry
  arg-type) — both in files I did not touch (confirmed present in the P3-01/02/03 reports). All
  new/changed files type-clean under `--strict`.
- `.venv/bin/python -m pytest -q` (no DB) → **183 passed, 41 skipped** (skips = live-DB suites;
  was 169 passed before this task → +14 new/updated tests).
- **Full suite against live Postgres + Redis** (brought the docker stack up, migrated head) →
  **224 passed, 0 skipped** — including the P3-04-modified live-DB e2e
  `test_restart_preserves_account_history_via_router_path_live_postgres`, which now authenticates
  through the real router and still proves account history survives a restart. (One harmless
  pre-existing `joserfc` short-test-key `SecurityWarning`, not a failure.)
- No test failures. No test weakened/deleted; the modified P2 e2e test was updated to the new
  auth contract (identity from token, not body), not loosened.

## Self-check
- [x] Meets acceptance criteria: cross-user (cross-session) access denied (`403`); guest 10th
  message ok / 11th denied (`429` upgrade prompt); guest upload 1 ok / 2nd denied; logged-in
  users have their own generous Redis-enforced limit; state keyed off the P3-01/02 session/user
  id; tests cover all four.
- [x] No secrets committed (limits are non-secret config; signing key still env/Space-secret
  only). Router→Service→Repository layering respected; interface-before-implementation
  (`RateLimiter` port before the Redis adapter; authZ/rate-limit deps in `security/` below `api/`).
- [x] Tests/lints pass (see above); pre-existing mypy noise called out, not introduced.
