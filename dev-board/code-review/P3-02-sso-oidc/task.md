# Task P3-02-sso-oidc — SSO OIDC (Google/LinkedIn) + session JWT + logout
- **Phase:** P3   **Status:** pending   **Tags:** (B)(I)

## Scope
This task folds together three related tasks.md bullets that form one coherent flow:
- "SSO via Authlib OIDC (Google + LinkedIn), backend-owned: `GET /api/auth/login/{provider}` + `GET /api/auth/callback/{provider}` with PKCE."
- "Mint short-lived session JWT; FastAPI verify dependency; `POST /api/auth/logout`."
- "OAuth apps for Google + LinkedIn; client secret + JWT signing key in HF Space Secrets; redirect URIs locked to Space domain; minimal scopes (`openid email profile`)."

Implement:
1. `GET /api/auth/login/{provider}` (`provider` in `google`, `linkedin`) — starts the Authlib OIDC flow with PKCE, redirects to the provider's consent screen with `openid email profile` scopes only.
2. `GET /api/auth/callback/{provider}` — completes the OIDC exchange, upserts a `users` row (id, provider, sub, email, display name — no password hashes), mints a short-lived backend-owned session JWT, and returns/redirects with it to the frontend.
3. A FastAPI dependency (e.g. `get_current_user` / `require_auth`) that verifies the session JWT (signature, expiry) and resolves the caller's user — reusable by all protected routes going forward.
4. `POST /api/auth/logout` — invalidates the session (Redis-backed session record and/or JWT denylist if you need immediate revocation; a short JWT TTL alone is acceptable if documented as the chosen tradeoff).
5. Config/secrets wiring in `app/config.py` (pydantic-settings): `GOOGLE_CLIENT_ID/SECRET`, `LINKEDIN_CLIENT_ID/SECRET`, `JWT_SIGNING_KEY`, redirect URIs — all read from env/Space secrets, never hardcoded. Since registering real OAuth apps in Google/LinkedIn consoles requires an external account outside this repo, you cannot create the actual OAuth apps — instead: wire the settings/config plumbing completely, add a `.env.example` entries, and write a short `docs/oauth-setup.md` (or README section) with the exact manual steps a human must do (create OAuth client, set redirect URI to `<space-domain>/api/auth/callback/{provider}`, minimal scopes) so this is a copy-paste checklist, not guesswork.
6. Local/dev/test story: since real provider credentials won't be available in CI/dev by default, make sure the OIDC integration is testable without live network calls (mock Authlib's OIDC discovery/token exchange in tests, or provide a fake/dev provider). Don't gate all tests on live Google/LinkedIn secrets being present.

## Acceptance criteria
- [ ] `GET /api/auth/login/{provider}` redirects to provider consent URL with PKCE challenge and minimal scopes.
- [ ] `GET /api/auth/callback/{provider}` exchanges code, verifies PKCE, upserts `users`, mints session JWT, no password ever stored.
- [ ] JWT is short-lived, signed with a key from Space secrets/env (never committed), and a reusable FastAPI dependency verifies it on protected routes.
- [ ] `POST /api/auth/logout` ends the session.
- [ ] Redirect URIs are derived from config (locked to the deployed domain), not hardcoded per-provider magic strings.
- [ ] Tests cover the JWT mint/verify/expiry logic and the callback flow against mocked provider responses — pass without real Google/LinkedIn credentials.
- [ ] `docs/oauth-setup.md` (or equivalent) documents the manual OAuth-app registration steps.

## Design references
- dev-board/app-design-and-features.md: §6.2 (auth model decision), §7.1 (SSO / data-protection: PKCE, short-lived JWT, Space secrets, no passwords), §7 API table.
- dev-board/plan.md: P3 — Auth, sessions & guest mode.

## Constraints / non-goals
- LinkedIn *profile import* (extra scopes, stored provider token) is a separate opt-in feature — out of scope; login only needs `openid email profile`.
- Guest→account upgrade logic is P3-03, not here (but this task's JWT/session shape must be compatible with it).
- AuthZ enforcement (own-data-only) and rate limits are P3-04, not here.
