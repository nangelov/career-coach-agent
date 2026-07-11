# Task P3-01-guest-session — Guest session endpoint
- **Phase:** P3   **Status:** ENG   **Tags:** (B)

## Scope
Implement `POST /api/auth/guest` — starts an anonymous Redis-backed guest session (no Postgres persistence).
tasks.md item: "`POST /api/auth/guest` → anonymous Redis session (TTL, no history)."

## Acceptance criteria
- [ ] `POST /api/auth/guest` creates a session record in Redis with a TTL (reuse/extend the P1 Redis session-memory pattern from `repositories/redis.py`).
- [ ] Response gives the client something to authenticate subsequent requests with (e.g. a guest session token/JWT distinguishing `role=guest` from logged-in — coordinate shape with the session-JWT work planned in P3-02 so both endpoints issue a compatible bearer token the frontend can treat uniformly).
- [ ] Guest sessions never write to Postgres `conversations`/`messages` (guests stay Redis-only per design).
- [ ] Guest session carries whatever state is needed later to enforce the 10-message + 1-upload guest rate limit (P3-04) — e.g. a session id usable as a Redis rate-limit key.
- [ ] No auth required to call this endpoint (it's how a guest starts).
- [ ] Unit/integration tests for the endpoint (creation, TTL, shape of response).

## Design references
- dev-board/plan.md: P3 — Auth, sessions & guest mode
- dev-board/app-design-and-features.md: §4 (Guest login row), §6.2 (auth model), §7 API table (`POST /api/auth/guest`), §7.1 (SSO/session model, for consistent token shape)

## Constraints / non-goals
- No SSO/OIDC in this task (that's P3-02).
- No rate-limit *enforcement* logic yet (that's P3-04) — just make sure the session carries what's needed.
- Do not touch the v1 legacy code.
