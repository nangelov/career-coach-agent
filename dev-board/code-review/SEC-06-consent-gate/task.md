# Task SEC-06-consent-gate — Consent gate (ToS + privacy acceptance)
- **Phase:** SEC   **Status:** ENG   **Tags:** (B/F)

## Scope
Design §6.22 / §7.6: **no session is minted without acceptance of the ToS + privacy notice.**
- **SSO login:** a checkbox on the login screen; acceptance is recorded against the user with
  the **policy version + timestamp** (so a policy change can re-prompt).
- **Guest:** the same gate at **every** guest-session start (each guest session is new, so
  consent is per-session, not durable).

This builds directly on **SEC-04** (already done — Next.js BFF Route Handlers for
`/api/auth/guest`, `/api/auth/login/{provider}`, `/api/auth/callback/{provider}`) and the login
UI (`frontend/components/Login.tsx`).

### Backend
1. **Policy version constant** — add a single source of truth for the current policy version
   (e.g. `settings.CONSENT_POLICY_VERSION` in `app/config.py`, a simple string like `"2026-07-13"`
   or `"1.0"`). Bumping it later is the mechanism that forces re-consent.
2. **Persist SSO consent.** `users` has no consent columns yet — add a migration (new Alembic
   revision, following the existing `backend/migrations/versions/` pattern) adding
   `consent_policy_version: str | None` + `consent_accepted_at: datetime | None` to `users`.
   Record these at the point the user row is created/updated (the OIDC callback flow,
   `SsoAuthService` / wherever `users` rows are upserted in `backend/app/services/auth.py`) —
   **only if the incoming login request actually carried consent** (see below); otherwise
   reject before completing the login.
3. **Carry consent through the OAuth redirect.** The checkbox is ticked on the login screen,
   *before* the full-page navigation to `GET /api/auth/login/{provider}` (PKCE) —
   `users` doesn't exist yet at that point (it's created/updated at the callback). Thread a
   `consent=1` (and implicitly "as of `CONSENT_POLICY_VERSION`") signal from the login request
   through to the callback so it can be persisted once the user row exists. The existing
   `oauth_state_store` (Redis, keyed by OAuth `state`) is the natural place to stash this small
   flag alongside whatever it already carries for PKCE — check
   `backend/app/services/oauth_state_store.py` / `RedisOAuthStateStore` before inventing a
   second mechanism. Reject the login attempt (before redirecting to the provider) if consent
   wasn't provided.
4. **Gate `POST /api/auth/guest`.** Require the request to indicate consent (e.g. a JSON body
   `{"consent": true}` or a query/header flag — pick something simple and consistent with how
   the endpoint is called today) matching the current policy version; reject with `400`
   otherwise. Guests don't get a durable consent record (nothing durable for a guest at all —
   consistent with §6.18 guest retention), but the created session may reasonably carry the
   accepted policy version in its Redis record for the life of that session (useful for
   support/debugging, not required for correctness).
5. **Re-prompt on version bump.** If an SSO user's stored `consent_policy_version` doesn't match
   `settings.CONSENT_POLICY_VERSION`, the *next* login must re-collect consent (the login screen
   already re-shows the checkbox on every fresh login — this is naturally satisfied as long as
   step 2/3 re-checks and re-records on every login, not just first-ever signup). You do **not**
   need to force-logout an already-active session mid-flight when the policy bumps — re-prompt
   happens at the next login, which is an acceptable, documented scope boundary.

### Frontend
6. **Checkbox on the login screen** (`frontend/components/Login.tsx`): "I agree to the [Terms of
   Service] and [Privacy Notice]" (links can point to placeholder routes — SEC-07 builds the
   actual pages right after this task; use `/terms` and `/privacy` as the hrefs now so SEC-07
   just has to fill them in). Both SSO buttons and the guest button must be **disabled until the
   checkbox is checked** (client-side UX gate — the backend gate in steps 3/4 is the real
   enforcement, this is just not making users hunt for why the button doesn't work).
7. **Wire the consent flag through**: `beginSsoLogin(...)` (in `frontend/lib/auth.ts`) needs a
   way to pass the consent flag to `GET /api/auth/login/{provider}` (query param is fine,
   consistent with how `upgradeTicket` is already passed there); `createGuestSession(...)` needs
   to send the consent flag/body the backend now requires.
8. **Handle the backend rejection** gracefully (e.g. the guest call now 400s if consent is
   missing — should not normally happen since the button is disabled, but don't let it crash;
   show the existing error banner pattern).

## Acceptance criteria
- [ ] `POST /api/auth/guest` rejects a request with no consent flag; succeeds when consent is
      present, and the session records include which policy version was accepted somewhere.
- [ ] SSO login flow: attempting `GET /api/auth/login/{provider}` without consent is rejected
      (before redirecting to the provider); with consent, the callback persists
      `consent_policy_version` + `consent_accepted_at` on the `users` row.
- [ ] A returning SSO user whose stored `consent_policy_version` is stale gets re-recorded (and,
      by construction of "re-prompt = next login shows the checkbox again", effectively
      re-prompted) on their next login.
- [ ] Login screen shows the checkbox; SSO + guest buttons are disabled until checked; links to
      `/terms` and `/privacy` (placeholder routes, filled in by SEC-07).
- [ ] Migration adds the two `users` columns cleanly (upgrade/downgrade both work).
- [ ] Tests: guest rejected without consent / accepted with consent; SSO login rejected without
      consent; callback persists policy version + timestamp; frontend button disabled state.

## Design references
- dev-board/app-design-and-features.md §6.22 "Consent" (also referenced in §7.6).
- dev-board/tasks.md — SEC block, item **S13**. Explicitly noted to ship alongside S4
  (already done) since it's the same session-creation surface.

## Constraints / non-goals
- Do not write the actual ToS/privacy notice **content** — that's **SEC-07** (Privacy notice +
  ToS pages), the very next task. Placeholder routes/links only here.
- Do not force-invalidate already-active sessions on a policy bump (documented scope boundary
  above).
- Do not add an admin consent-audit UI (deferred with the rest of the admin panel to P12
  pre-go-live per the design).
