---
name: auth-protected-endpoint-tests
description: How to auth-gate an existing endpoint + keep its API tests green (require_auth/rate-limit dependency overrides, identity from token not body)
metadata:
  type: project
---

Adding auth/rate-limits to a previously-open endpoint (e.g. P3-04 on `/api/chat`).

**Why:** identity must come from the verified session JWT (`CurrentUser` via `require_auth`),
never a client-sent body field — a client-controlled `user_id` is an authZ hole. Own-data-only
is centralized in `security/dependencies.authorize_session_access(session_id, current_user)`
(403 on mismatch), called in-handler *before* the rate-limit enforce so a rejected cross-session
request doesn't consume budget.

**How to apply:**
- Router derives `user_id=current_user.user_id`; drop the interim body `user_id` field.
- Rate limiting: `RateLimitService` (policy, services/rate_limiting.py) over a `RateLimiter` port
  (Redis `INCR`+first-hit `EXPIRE` fixed window in repositories/redis.py). Wire via
  `bootstrap.build_rate_limit_service` + `get_rate_limit_service` dep + `RATE_LIMIT_SERVICE` state key.
- Existing/new API tests: override BOTH `app.dependency_overrides[require_auth] = lambda: fake_current_user(...)`
  and `[get_rate_limit_service] = unlimited_rate_limit_service` (both helpers live in `tests/fakes.py`).
  Use `app.dependency_overrides.clear()` in `finally`. A no-override request now returns 401, not 422.
- Guest cap keys on `session_id` (per-session, TTL=session window); user cap keys on `user_id`
  (per-window, resets). See [[project-auth-session-jwt]] and [[project-composition-root]].
