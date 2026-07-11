# Engineer report — P3-06-login-ui · Revision 1

## Summary
Implemented the frontend login UI and bearer-session handling on top of the P3-01/P3-02/P3-04
backend. Users can now start as guest or sign in with Google/LinkedIn from a login screen;
the session JWT is stored client-side and attached as a `Authorization: Bearer` token on chat
calls; an expired/invalid session (401) falls back to login; and a guest rate-limit rejection
(429) renders an "upgrade to continue" prompt (preserving the session via an upgrade ticket)
rather than a raw error. The OIDC redirect-callback landing page (`/auth/callback`) reads the
token from the URL fragment and routes into the chat.

The chat is now **auth-gated**: with no session it renders `<Login>`, matching the backend
where every `/api/chat` call requires a bearer token.

## Files changed
New:
- `frontend/lib/auth.ts` — auth client: `Session` model (mirrors backend `GuestSessionResponse`/
  `SessionResponse`), localStorage persistence with expiry, `createGuestSession`,
  `beginSsoLogin`, `upgradeGuestToSso`, `logout`, `sessionFromFragment`/`sessionFromPayload`,
  `authHeaders`. All flows take injectable `fetchImpl`/`navigate` for testability.
- `frontend/components/Login.tsx` — login screen: Continue with Google / LinkedIn / guest.
- `frontend/components/UpgradePrompt.tsx` — 429 "upgrade to continue" prompt (guest → SSO
  upgrade that preserves the conversation; user → back-off/dismiss).
- `frontend/app/auth/callback/page.tsx` — SSO post-login landing; parses the fragment token,
  persists it, `router.replace("/")`; failure state on a tokenless fragment.
- Tests: `frontend/__tests__/auth.test.ts`, `Login.test.tsx`, `authCallback.test.tsx`.

Modified:
- `frontend/lib/chatStream.ts` — added `token` option (Bearer header) to `streamChat`/
  `cancelChat`; map HTTP 401 → synthetic `auth_error` event and 429 → `rate_limited` event
  (carrying the backend `detail` + `Retry-After`), leaving other non-2xx as generic `error`.
- `frontend/components/Chat.tsx` — resolve session via `loadSession()` (replaces the old
  client-minted `sessionStorage` id); render `<Login>` when unauthenticated; attach token to
  chat/cancel; handle `auth_error` (drop credential → login) and `rate_limited` (upgrade
  prompt); added a header role indicator + Log out button.
- `frontend/__tests__/Chat.test.tsx`, `page.test.tsx` — seed a valid session (chat is now
  auth-gated) and added coverage for token attachment, rate-limit prompt, and 401 fallback.

## Key decisions
- **Client-side token storage (localStorage), not a cookie** — P3-02's callback returns the
  token in the URL *fragment* (`app/api/auth.py` `sso_callback`), so an httpOnly cookie is not
  available; the token can only live client-side. localStorage (over sessionStorage) is chosen
  so an SSO account stays logged in across reloads — the point of "accounts + saved history"
  (§5). Expiry is enforced on load and the token is cleared on logout/401. (design §6.2/§7.1)
- **Uniform session shape for guest and user** — `lib/auth.Session` mirrors the backend's
  single token shape (`GuestSessionResponse`/`SessionResponse`), so the frontend handles both
  identity kinds with one code path (§7.1).
- **401/429 surfaced as distinct client-synthesized stream events** (`auth_error`,
  `rate_limited`) rather than the generic `error` — the UI must act on them differently
  (redirect to login vs. upgrade prompt). They never appear on the wire; this mirrors how the
  transport already synthesizes `error` for network failures. (§6.8/§7)
- **Guest upgrade preserves the conversation** — the 429 prompt mints a single-use upgrade
  ticket (`POST /api/auth/upgrade`) and appends it to `GET /api/auth/login/{provider}`, so the
  active guest session carries into the new account (§4 upgrade-to-account). Falls back to a
  plain login if ticket minting fails.
- **Layering** — transport/auth logic lives in `lib/` (§8 "api client / auth"), UI in
  `components/`, route in `app/`; components depend on `lib`, not vice versa.

## How to verify
- `cd frontend && npm test` — full Jest suite.
- `npm run type-check` and `npm run lint` — clean.
- `npm run build` — `/auth/callback` compiles as a static route.
- Manual: with the backend running, load the app → login screen → "Continue as guest" starts a
  session and shows the chat; send messages until the guest cap → upgrade prompt appears; the
  Google/LinkedIn buttons redirect through the backend OIDC flow and land on `/auth/callback`.

## Tests (final step — mandatory)
- `npm test` → **6 suites / 50 tests passed**.
- `npm run type-check` (`tsc --noEmit`) → clean.
- `npm run lint` (`next lint`) → No ESLint warnings or errors (fixed an initial
  `no-html-link-for-pages` finding by using `next/link` in the callback page).
- `npm run build` → Compiled successfully; routes `/` and `/auth/callback` generated.
- No failing tests. I updated `Chat.test.tsx`/`page.test.tsx` to seed a session because the
  chat is now legitimately auth-gated (they previously asserted the pre-auth behavior of a
  client-minted id); this is a behavior change from this task, not a weakened test — new
  assertions for the login screen, token attachment, rate-limit, and 401 were added.

## Self-check
- [x] Meets acceptance criteria: guest + Google/LinkedIn from UI; token carried on requests;
      expired session → login; 429 → upgrade prompt; component tests for render + button →
      fetch/navigation.
- [x] No secrets committed; layering respected (lib transport/auth ← components ← app route).
- [x] Tests/lints/build pass (results above).
