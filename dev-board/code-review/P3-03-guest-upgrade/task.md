# Task P3-03-guest-upgrade — Guest → account upgrade preserves session
- **Phase:** P3   **Status:** pending   **Tags:** (B)

## Scope
tasks.md item: "Guest → account upgrade preserves the active session."
When a guest (holding a guest session from P3-01) completes SSO login (P3-02), the *same* active session
(conversation-in-progress, remaining rate-limit counters if relevant, thread state) is carried over to the
newly created/linked account rather than starting fresh. Concretely: the guest's in-Redis session
history/state should be attached to the authenticated user after login (e.g. re-keyed from the guest
session id to the user's session, and if design calls for persisting it, written into Postgres
conversations/messages at that point since the user is no longer a guest).

## Acceptance criteria
- [ ] A guest can start chatting, then hit login, complete SSO, and land back in the same conversation
      (not a blank one).
- [ ] Post-upgrade, the conversation begins persisting to Postgres (since the user is no longer a guest),
      per the P2 persistence path for logged-in users.
- [ ] The mechanism for "which guest session upgrades to which new session" is safe (e.g. a short-lived
      upgrade token/state param tying the OIDC flow back to the originating guest session — avoid trusting
      a client-supplied guest id blindly).
- [ ] Tests cover: guest session + upgrade → history preserved; no cross-contamination between unrelated
      guest sessions upgrading concurrently.

## Design references
- dev-board/app-design-and-features.md: §4 (Guest login row: "Upgrade-to-account preserves current session"), §6.2.
- dev-board/plan.md: P3.

## Constraints / non-goals
- Rate-limit reset/carry-over policy: once upgraded the user is no longer guest-rate-limited — just make sure the transition is clean; the rate-limit implementation itself is P3-04.
