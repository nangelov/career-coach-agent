# Task P3-06-login-ui — Login UI + bearer session handling
- **Phase:** P3   **Status:** pending   **Tags:** (F)

## Scope
tasks.md item: "Login UI (Google/LinkedIn buttons, guest button) + session handling (Bearer token)."
Frontend (Next.js App Router) work:
1. A login screen/component with "Continue with Google", "Continue with LinkedIn", and "Continue as guest"
   buttons, wired to the backend endpoints from P3-01/P3-02.
2. Client-side session handling: store the session JWT (from guest or SSO login) securely (httpOnly cookie
   set by backend is preferable to localStorage if the backend supports it — check what P3-02 actually
   returns and match it), attach it as a Bearer token on API calls (chat, profile, etc.), and handle
   401/expired-session by redirecting to login.
3. Handle the OIDC redirect-callback landing page/flow on the frontend side (whatever P3-02's callback
   redirects to).
4. Surface the guest rate-limit-exceeded response (from P3-04) as an "upgrade to continue" prompt in the UI.

## Acceptance criteria
- [ ] User can start as guest, or sign in with Google/LinkedIn, from the UI.
- [ ] Authenticated requests carry the session token correctly; expired/invalid session redirects to login.
- [ ] Guest rate-limit responses show an upgrade prompt rather than a raw error.
- [ ] Basic component tests (render, button click triggers navigation/fetch to the right endpoint).

## Design references
- dev-board/app-design-and-features.md: §6.2, §4 (guest login row), §8 (frontend structure: `components/`, `lib/` — auth client).
- dev-board/plan.md: P3.

## Constraints / non-goals
- Visual polish/branding is secondary to functional correctness — keep it simple and consistent with the
  existing P1 chat UI styling.
