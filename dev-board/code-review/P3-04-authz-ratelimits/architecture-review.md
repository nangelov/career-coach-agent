# Architecture review — P3-04-authz-ratelimits · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure / layering | Router → Service → Repository; deps in `security/` (below `api/`); driver only in `repositories/` | `api/chat.py` thin (authZ + rate-limit checks, no business logic) → `services/rate_limiting.py` policy → `RateLimiter` port → `repositories/redis.py::RedisRateLimiter` adapter; authN/authZ/rate-limit deps in `security/dependencies.py` | none |
| A2 | Interface-before-implementation (§8 idiom) | Real seam for rate limiting so storage is swappable | `RateLimiter` ABC + `InMemoryRateLimiter` test double in the service module; `RedisRateLimiter` (Redis adapter) in the repo layer; narrow `LimiterRedis` Protocol so no hard driver type leaks | none |
| A3 | Decision 8 (§6 #8, §4 guest row, §5) | Guest capped at **10 messages + 1 document upload per guest session**; exceeding either prompts upgrade | `GUEST_MAX_MESSAGES=10`, `GUEST_MAX_UPLOADS=1`; `RateLimitService._policy` keys guest on `session_id`; 429 detail contains "Sign in to continue"; upload action a first-class `RateLimitAction` enforced at the service boundary (route lands P5) | none |
| A4 | §7 AuthZ ("users can only read their own …") — centralized, not per-route | One own-data check reused across session-scoped routes | `authorize_session_access(session_id, current_user)` — single helper in `security/`, reused by `POST /api/chat` + `POST /api/chat/{session}/cancel`; 403 on `session_id != token.sid` | none |
| A5 | §7 AuthZ — identity from the verified token, not client input | Turn `user_id` must derive from the JWT, not the request body | Client-controlled `user_id` removed from `ChatRequest`; `chat` sources `user_id=current_user.user_id`; closes the P2 "not an authorization boundary" interim seam and the P1 "anyone who knows a session_id can cancel it" gap (A10 from P3-02 review) | none |
| A6 | §4 data ownership — guests Redis-only, user-scoped | Guest budget on Redis keyed by anonymous session; user budget keyed on `users.id` | Guest keyed `guest:<action>:<session_id>`; user keyed `user:<action>:<users.id>` (follows the user across sessions); Redis-only, no Postgres wiring | none |
| A7 | §4 Redis single shared pool ("no per-request clients") | Limiter over the one shared `redis.asyncio` pool | `build_rate_limit_service` acquires `_shared_redis_client(app)`; counter reuses the shared pool; `RedisConnectionProvider` unchanged | none |
| A8 | Composition-root wiring (blessed bootstrap.py pattern) | Assembled once in `bootstrap.py`, cached on `app.state`, dependency-overridable in tests | `build_rate_limit_service` + `AppStateKeys.RATE_LIMIT_SERVICE`; `get_rate_limit_service` caches on state; tests override with an in-memory limiter | none |
| A9 | §11 budget posture | Free/OSS/self-hosted; no paid tier | Redis fixed-window counter only; limits are non-secret config | none |
| A10 | Phase fit (P3) | AuthZ + rate limits for endpoints existing through P2; admin auth stays P3-05 | Applied to the only user-scoped routes that exist (chat + cancel); `/get-feedback` untouched; auth-flow routes (guest/upgrade/login/callback/logout) are not cross-user data and logout already keys on the caller's own `session_id` | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Repository); deps in `security/`, driver in `repositories/`.
- [x] Honors locked decisions — Postgres+Redis only (Redis-only here); SSO-derived identity trusted over client input; guest cap = Decision 8.
- [x] Interfaces-before-implementations — `RateLimiter` port precedes the Redis adapter; `LimiterRedis` Protocol seam.
- [x] Budget posture respected (free/OSS/self-hosted).
- [x] AuthZ centralized (one `authorize_session_access` helper), not duplicated ad hoc per route.

## Notes
- **AuthZ model is correct for the current data shape.** The token's `sid` *is* the caller's session boundary, so
  "session_id must equal the token's sid" is the whole own-data rule for chat/cancel — no repository-level scoping
  query is needed yet. When user-owned relational rows land (profile/dashboard/jobs in P5+), the own-data check will
  need a **repository/query-level** owner filter (`WHERE user_id = :caller`), not just the session-equality helper.
  The centralization here is the right seam to extend; flag it as the P5 follow-up, not a gap now (correctly YAGNI today).
- **Fixed-window vs. session-lifetime (minor, by design).** The guest counter is a fixed 24h window (== session TTL)
  keyed on `session_id`; a guest getting a fresh budget by minting a *new* guest session is inherent to the anonymous
  guest model (§4) and not preventable here — "per guest session" is exactly the decided semantics. Within one session
  the budget holds (window ≥ JWT lifetime). No action.
- **Eager message count (minor).** The message is counted before the stream opens, so a turn that later errors still
  consumes one unit of budget. Acceptable fixed-window behavior; authZ runs *before* the count (tested), so a rejected
  cross-session request never spends budget.
- **`INCR`+`EXPIRE` non-atomic (already noted in-code).** Two-command window where a crash could leave a TTL-less
  counter; short window + self-namespaced key make impact negligible. A Lua/pipeline atomic variant is a fine future
  hardening — logged, not required.
