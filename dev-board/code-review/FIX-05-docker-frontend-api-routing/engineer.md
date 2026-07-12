# Engineer report — FIX-05-docker-frontend-api-routing · Revision 1

## Summary
Under `docker compose up --build`, every frontend `/api/*` call (guest login, SSO, chat, profile) 404'd
inside the Next.js server because the dev-only `rewrites()` proxy was disabled outside `next dev` and there
is no reverse proxy in the two-container compose topology.

**Chosen approach: Option 1 — always-on, configurable same-origin rewrite proxy.** The browser keeps talking
only to the Next.js origin (`:3000`); the Next.js server reverse-proxies `/api/*` to the backend. This keeps
the deployment **same-origin (no CORS)** — matching the codebase's stated preference — and requires **zero**
changes to the client bundle or the `lib/*` API clients (their `baseUrl = ""` default is preserved).

**Critical nuance discovered and handled:** Next.js evaluates `rewrites()` at **build time** and freezes the
destination into `.next/routes-manifest.json`; `next start` does **not** re-read the env var at runtime
(proven empirically — see Tests). So `INTERNAL_API_URL` is passed as a Docker **build ARG**, not a runtime
`environment:` entry (the task's Option-1 sketch assumed runtime; the build-time freezing is the same gotcha
the task flagged for `NEXT_PUBLIC_*`). Bare `docker build` / `next dev` / `next start` default to
`http://localhost:8000` (unchanged behavior); docker-compose overrides the ARG to `http://backend:8000`.

## Files changed
- `frontend/lib/apiProxy.ts` (new) — pure, unit-testable helper: `resolveInternalApiBaseUrl(env)` +
  `buildApiRewrites(env)`. Reads `INTERNAL_API_URL` (default `http://localhost:8000`), trims trailing slash.
  Documents the build-time-freezing behavior.
- `frontend/next.config.ts` — `rewrites()` now always-on (removed the `NODE_ENV !== "development"` guard) and
  delegates to `buildApiRewrites()`; destination parameterized instead of hard-coded.
- `frontend/Dockerfile` — builder stage adds `ARG INTERNAL_API_URL=http://localhost:8000` + `ENV` before
  `npm run build`, so the backend host is baked into the manifest at build time.
- `docker-compose.yml` — `frontend.build.args.INTERNAL_API_URL: http://backend:8000` (compose service DNS),
  with a comment explaining why it's a build arg not a runtime env.
- `frontend/__tests__/apiProxy.test.ts` (new) — regression tests: default/blank/set/trailing-slash resolution,
  and the key guard that the `/api/:path*` proxy is emitted **unconditionally** (the exact FIX-05 regression).
- `.env.example` — informational note on the frontend→backend proxy and that `INTERNAL_API_URL` is a build arg
  (set in docker-compose), not read from `.env`.

## Key decisions
- **Option 1 over Option 2 (CORS):** same-origin proxy needs no CORS, no `NEXT_PUBLIC_*` client inlining, and
  no edits to `lib/auth.ts`/`lib/chatStream.ts`/`lib/profile.ts` (design ref: their `baseUrl` DI seam +
  `next.config.ts` "avoid CORS and hard-coded hosts" comment). KISS/DRY: one env-driven destination, one seam.
- **Build ARG, not runtime env:** forced by Next.js freezing `rewrites()` into `routes-manifest.json` at build
  (verified — see Tests). Documented in code + compose so the next person doesn't mis-set it at runtime.
- **SSO redirect URLs unchanged:** `OAUTH_REDIRECT_BASE_URL=http://localhost:8000` and
  `OAUTH_POST_LOGIN_REDIRECT=http://localhost:3000/auth/callback` remain correct — the login initiation
  proxies through `:3000`, but the OAuth `redirect_uri` (where Google returns the browser) is the directly
  exposed backend `:8000`, and post-login lands back on the frontend `:3000`. Live test confirms the 302 to
  Google carries `redirect_uri=http://localhost:8000/api/auth/callback/google`. No change needed.
- **`next dev` no-regression:** with `INTERNAL_API_URL` unset the destination is `http://localhost:8000` —
  byte-identical to the old dev-only rewrite.

## How to verify
- Local: `cd frontend && npx jest && npx next lint && npx tsc --noEmit`.
- Live: `docker compose up -d --build`, then
  `curl -X POST http://localhost:3000/api/auth/guest` → **201** with a real backend JWT (not a Next.js 404);
  `curl http://localhost:3000/api/auth/login/google` → **302** to `accounts.google.com`.

## Tests (final step — mandatory)
**Build-vs-runtime proof (why a build ARG is required):** built the frontend with
`INTERNAL_API_URL=http://buildtime-sentinel:9999` → `routes-manifest.json` destination =
`http://buildtime-sentinel:9999/api/:path*` (baked). Then rebuilt with the default and ran `next start` with a
**different** runtime `INTERNAL_API_URL=http://localhost:9111`: the proxy still targeted `http://localhost:8000`
(the build-time value) — confirming runtime env is ignored, so `build.args` is mandatory.

**Frontend jest:** `10 passed, 95 tests` (incl. new `apiProxy.test.ts`).
**Frontend lint:** `✔ No ESLint warnings or errors`. **Type-check:** `tsc --noEmit` clean.

**Backend gate (unchanged code, run per acceptance):**
- `make lint` (ruff) → `All checks passed!`
- `make typecheck` (mypy) → `Success: no issues found in 94 source files`
- `make test` (pytest) → `411 passed, 49 skipped` (integration suites skip cleanly without a live DB, as in CI).

**Live docker-compose verification** (`docker compose up -d --build`, all containers healthy):
```
# frontend image baked destination:
#   { source: '/api/:path*', destination: 'http://backend:8000/api/:path*' }

### uncovered path still 404s from Next.js (baseline):
GET /nope via :3000 -> HTTP 404

### THE FIX — guest login through the frontend proxy:
$ curl -i -X POST http://localhost:3000/api/auth/guest
HTTP/1.1 201 Created
content-type: application/json          # note: NO X-Powered-By: Next.js — backend answered
{"access_token":"eyJ0eXAiOiJKV1Q...","token_type":"bearer",
 "session_id":"c35926a1a5fc4acca2b92ba93be50b70","role":"guest","expires_in":3600}
$ curl ... :8000/api/auth/guest -> HTTP 201    # direct-backend baseline matches

### SSO (Continue with Google) through proxy — no longer a Next.js 404:
GET :3000/api/auth/login/google -> HTTP 302
location: https://accounts.google.com/o/oauth2/v2/auth?...&redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fauth%2Fcallback%2Fgoogle&...

### Profile surface (guest GET /api/profile) through proxy:
{"skills":[],"experience":[],"education":[],"goals":[]}  -> HTTP 200

### Chat surface (guest POST /api/chat) through proxy — full SSE round-trip from backend:
event: start   data: {"message_id":"9d367db7..."}
event: plan    data: {"intent":"chat","steps":["Answer the user's message directly."],"workers":[]}
event: token   data: {"content":"I'm sorry — I'm having trouble generating a response right now..."}
event: done    data: {"message_id":"9d367db7...","finish_reason":"error","citations":[]}
```
(The chat `token` is the backend's graceful LLM-error fallback — the HF model isn't reachable in this
sandbox — but the entire SSE pipeline round-tripped through `:3000 → backend:8000`, proving routing.)
Stack torn down afterward with `docker compose down` (all containers + network removed).

## Self-check
- [x] Meets acceptance criteria — guest login 201 (no 404/CORS); SSO 302 to Google; `next dev` default
      unchanged; chat + profile surfaces spot-checked live; ruff/mypy/pytest + jest/lint/build all pass;
      report includes the actual `docker compose up` evidence.
- [x] No secrets committed; no new backend layering (frontend/infra-only change).
- [x] Tests/lints pass (pasted above).
