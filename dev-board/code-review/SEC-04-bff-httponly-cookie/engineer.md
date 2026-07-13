# Engineer report — SEC-04-bff-httponly-cookie · Revision 2

## Summary
Replaced the `localStorage` + client-Bearer session transport with a **Next.js BFF**: an
httpOnly · Secure(prod) · SameSite=Lax cookie (`cc_session`) holds the session JWT, and Route
Handlers under `app/api/*` inject `Authorization: Bearer <token>` **server-side** on every
proxied call. The token never enters browser JS and never appears in a URL. SSE chat streaming
passes through the catch-all handler unbuffered. Added baseline security headers/CSP on the Next
origin. Backend AuthN/AuthZ unchanged (callback keeps its fragment redirect — now
server-to-server only, documented in-code).

## Files changed
**New — BFF (frontend):**
- `lib/bffSession.ts` — pure token helpers: `SESSION_COOKIE`, `decodeSessionToken` (unverified,
  display-only), `clientSessionState` (token-free projection), `sessionCookieMaxAge`.
- `lib/bffProxy.ts` — `proxyRequest` (streaming passthrough + header injection/stripping),
  `setSessionCookie`/`clearSessionCookie`, `resolveBackendUrl`.
- `app/api/[...path]/route.ts` — catch-all GET/POST/PUT/DELETE/PATCH proxy (nodejs runtime).
- `app/api/auth/guest/route.ts` — mint guest, set cookie, return token-free body.
- `app/api/auth/session/route.ts` — hydration: reads cookie → token-free state.
- `app/api/auth/login/[provider]/route.ts` — server-side call to backend login, browser redirect
  to provider consent URL (redirects not auto-followed).
- `app/api/auth/callback/[provider]/route.ts` — server-side callback exchange, extracts token
  from the backend's fragment (Node-only), sets cookie, clean redirect to `/auth/callback`.
- `app/api/auth/logout/route.ts` — best-effort backend revoke + clear cookie.

**Rewritten (frontend client):**
- `lib/auth.ts` — token-free `Session` (`sessionId`/`role`/`expiresAt`); `fetchSession`,
  `createGuestSession`, `beginSsoLogin`, `upgradeGuestToSso`, `logout` now hit the BFF; removed
  `accessToken`/`localStorage`/`authHeaders`/`sessionFromFragment`.
- `lib/chatStream.ts` — dropped the client `token` option (BFF injects auth).
- `lib/profile.ts` — dropped `session`/`authHeaders`; same-origin fetches only.
- `lib/apiProxy.ts` — kept `resolveInternalApiBaseUrl`; removed `buildApiRewrites` (BFF replaces it).
- `components/Chat.tsx`, `components/CvUpload.tsx`, `components/ProfileView.tsx`,
  `components/UpgradePrompt.tsx`, `app/profile/page.tsx`, `app/auth/callback/page.tsx` — hydrate
  via `fetchSession`; drop token/session plumbing.
- `next.config.ts` — removed `/api/*` `rewrites()`; added security headers + CSP.

**Backend / infra:**
- `backend/app/api/auth.py` — comment only: why the fragment redirect is still safe (server-to-server).
- `docker-compose.yml` + `frontend/Dockerfile` — `INTERNAL_API_URL` moved from build ARG to
  runtime env (BFF reads it at request time; no longer build-frozen).

**Tests:** updated all affected suites + new `__tests__/bffSession.test.ts`,
`__tests__/bffProxy.test.ts`, `__tests__/bffAuthRoutes.test.ts`.

## Key decisions
- **Single httpOnly cookie + `/api/auth/session` hydration** (task's "pick one"): no second
  metadata cookie — avoids cookie/state drift; the session handler decodes the JWT claims
  (unverified, display-only) into a token-free body. Backend still verifies on every real call.
- **Catch-all `[...path]` handler** for the generic "forward + attach Authorization" shape;
  auth endpoints that need cookie/redirect logic get dedicated handlers; `auth/upgrade` falls
  through the catch-all (design §7.2, task item 1).
- **SSE**: `runtime = "nodejs"` + returning the undici `ReadableStream` body verbatim (strip
  `content-encoding`/`content-length`/`transfer-encoding`) keeps chat tokens incremental —
  verified by a proxy test that asserts `response.body` is a live `ReadableStream`.
- **Backend callback unchanged** (kept fragment redirect, now consumed only by the BFF Node
  process) to avoid touching AuthN logic — per the constraints. Added an in-code warning.
- **`INTERNAL_API_URL` is now runtime**, reversing the FIX-05 build-freeze constraint, because the
  BFF reads it per-request rather than via `rewrites()`.

## How to verify
- `cd frontend && npx jest` · `npx tsc --noEmit` · `npx next lint` · `npx next build`
- `cd backend && python -m pytest tests/ -q`
- Manual: guest → chat streams incrementally; SSO login (both providers) → clean `/auth/callback`
  URL, cookie set, no token in URL/localStorage; upgrade + logout clear/repoint the cookie.
  DevTools: `cc_session` is HttpOnly; no token in Application→Local Storage or any URL.

## Tests (final step — mandatory)
- **Frontend:** `npx jest` → **13 suites, 113 tests passed**. `npx tsc --noEmit` clean.
  `npx next lint` → no warnings/errors. `npx next build` succeeds (all `app/api/*` handlers
  registered as dynamic server functions).
- **Backend:** `python -m pytest tests/ -q` → **455 passed, 49 skipped** (auth subset: 26 passed).
- No failures. New Route-Handler tests run under `@jest-environment node` (jsdom lacks working
  `Request`/`Response`/`ReadableStream`); they assert cookie set/cleared, Authorization injected +
  client-supplied auth/cookie stripped, and **no token in the `/api/auth/guest` + `/api/auth/session`
  response bodies**.

## Self-check
- [x] Meets acceptance criteria (token never in localStorage/URL; Authorization only from BFF;
  cookie httpOnly/Secure-prod/SameSite=Lax; guest/SSO/upgrade/logout flows intact; SSE streams;
  security headers present; CORS stays closed — backend `ALLOWED_ORIGINS` untouched, not `*`).
- [x] No secrets committed; Router→Service→Repo layering respected (backend untouched beyond a
  comment; BFF is a thin transport layer).
- [x] Tests/lints pass (results above).

## Response to review (revision 2)

**C1 (major) — OIDC `redirect_uri` pointed at the now-unreachable backend origin.** Fixed. The
`redirect_uri` is derived by `SsoAuthService._redirect_uri` as
`<OAUTH_REDIRECT_BASE_URL>/api/auth/callback/{provider}` — this is both the value registered in
the provider console **and** where the provider redirects the *browser* after consent. Since
SEC-03 removed the backend's published port, that URL must resolve on the browser-reachable Next
origin (where the BFF callback Route Handler receives it and forwards to the backend
server-side). Changed the default and docs accordingly:
- `.env.example:34-42` — `OAUTH_REDIRECT_BASE_URL=http://localhost:3000` (was `:8000`); comment
  rewritten to say "FRONTEND / Next origin" and explain the SEC-03 reasoning.
- `backend/app/config.py:182-206` — `OAUTH_REDIRECT_BASE_URL` default → `http://localhost:3000`
  and docstring now describes the frontend/Next origin + BFF-forwarding chain. Also fixed the
  false `OAUTH_POST_LOGIN_REDIRECT` docstring: the fragment is read **server-side by the BFF**,
  not client-side.
- No backend logic changed (`_redirect_uri` derivation untouched); no test asserted these config
  values (`grep OAUTH_REDIRECT_BASE_URL/OAUTH_POST_LOGIN_REDIRECT backend/tests` → none). The
  `localhost:8000` literals in `test_oidc_client.py`/`test_oauth_state_store.py` are arbitrary
  `redirect_uri` *inputs*, unrelated to the config default; `test_sso_service.py` sets its own
  `https://app.example` base — all still pass.

**C2 (nit) — silent login failure.** Addressed. `app/api/auth/login/[provider]/route.ts` now
falls back to `/?login_error=<reason>` (`unknown_provider` for a backend 404, `provider_unavailable`
otherwise) instead of a bare redirect to `/`, giving the UI a signal to surface. Added a test for
the 502 → `provider_unavailable` path and updated the 404 assertion.

## Tests (revision 2)
- **Frontend:** `npx tsc --noEmit` clean; `npx jest` → **13 suites, 114 tests passed** (+1 new
  login-error test).
- **Backend:** `pytest tests/ -q` → **455 passed, 49 skipped**. No failures.
