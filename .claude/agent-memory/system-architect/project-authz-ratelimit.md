---
name: project-authz-ratelimit
description: Blessed P3-04 authZ + rate-limit pattern (own-data helper, RateLimiter port, guest Decision-8 caps) and the P5 repo-level owner-filter follow-up
metadata:
  type: project
---

P3-04 (authz + rate limits) APPROVED rev 1. Blessed patterns to keep consistent:

- **AuthZ centralized** in `security/dependencies.py::authorize_session_access(session_id, current_user)` —
  one helper reused by chat + cancel (and every future session-scoped route). Rule today =
  `session_id == token.sid` (the token's `sid` *is* the caller's session boundary). Runs **before** rate-limit
  so a rejected cross-session request never consumes budget.
- **Identity from the verified token, never client input.** `ChatRequest.user_id` was removed;
  `user_id=current_user.user_id`. Closed the P2 "not an authorization boundary" seam and the P1 cancel gap
  (A10 from P3-02 review). See [[project-auth-session-seam]].
- **Rate limits**: `RateLimiter` ABC port (in `services/rate_limiting.py`) + `RedisRateLimiter` fixed-window
  adapter (`INCR`+first-hit `EXPIRE`) in `repositories/redis.py` over the shared pool. `RateLimitService` policy
  keys guest on `session_id`, user on `users.id`. Guest caps = Decision 8 (10 msg + 1 upload/session,
  window=session TTL); user tier generous (120 msg/h, 20 uploads/h). Upload is a first-class `RateLimitAction`
  enforced at the service boundary now; P5 CV route wires it in one call.

**Why:** §7 AuthZ ("users read only their own data") + §6 Decision 8 guest cap; keep the rule in one place.

**How to apply (P5+ follow-up, not a gap now):** when user-owned *relational* rows land
(profile/dashboard/jobs), own-data enforcement must move to a **repository/query-level owner filter**
(`WHERE user_id = :caller`), not just session-equality. The `authorize_session_access` helper is the seam to
extend. A repo-scoping framework today would be YAGNI. Guest-gets-fresh-budget-by-new-session is inherent to
the anonymous guest model (§4), not a defect.
