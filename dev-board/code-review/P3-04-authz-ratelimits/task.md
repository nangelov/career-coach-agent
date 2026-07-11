# Task P3-04-authz-ratelimits — AuthZ (own-data-only) + Redis rate limits
- **Phase:** P3   **Status:** pending   **Tags:** (B)

## Scope
Two related tasks.md bullets:
- "AuthZ: users access only their own data; per-session/user rate limits in Redis."
- Enforce the already-decided guest rate-limit policy: **10 messages + 1 document upload per guest session**
  (the P3-01 guest session already carries what's needed as a Redis key; this task enforces it).

Implement:
1. AuthZ checks on every user-scoped endpoint (conversations, profile, jobs, memory, etc. — whichever exist
   so far from P0-P2) so a user can only read/write their own rows; reject cross-user access with 403/404 as
   appropriate. Centralize this rather than duplicating per-route (e.g. a repository-level or dependency-level
   scoping helper).
2. Redis-backed rate limiting: guests capped at 10 chat messages + 1 document upload per guest session
   (exceeding either should return a clear error prompting upgrade-to-account); logged-in users get a
   separate, more generous per-user/per-session limit (reasonable default — document the number chosen).
3. Rate limit state keyed off the session/user id established in P3-01/P3-02.

## Acceptance criteria
- [ ] A logged-in user's request for another user's conversation/profile/etc. is denied.
- [ ] A guest hitting the 11th chat message (or 2nd upload) gets a clear rate-limit response.
- [ ] Logged-in users have their own (more generous) rate limit, enforced in Redis.
- [ ] Tests cover: cross-user access denied; guest limit enforced at the boundary (10th ok, 11th denied);
      upload limit enforced (1 ok, 2nd denied).

## Design references
- dev-board/app-design-and-features.md: §4 (guest rate-limit row), Decision 8 in the decisions list (10 msgs + 1 upload), §7 (AuthZ bullet: "users can only read their own conversations/profiles; ... replaced with proper admin auth" — admin auth itself is P3-05).
- dev-board/plan.md: P3.

## Constraints / non-goals
- Admin-only feedback-dump auth is a separate task (P3-05) — don't need to touch `/get-feedback` here.
