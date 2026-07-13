---
name: project-bff-session-transport
description: Blessed SEC-04 BFF/httpOnly-cookie session transport — Route Handlers in frontend/app/api/*, token never in JS/URL, FIX-05 build-ARG ruling superseded by runtime env
metadata:
  type: project
---

SEC-04 (APPROVED, rev 1) implemented §7.2/§6.13 network-posture + session transport. Blessed patterns
(gate future frontend/auth-transport tasks on these):

- **BFF shape**: catch-all `frontend/app/api/[...path]/route.ts` (nodejs + `force-dynamic`) forwards all
  `/api/*` to the backend, injecting `Authorization: Bearer` from the httpOnly cookie server-side and
  **stripping** any client-supplied `authorization`/`cookie`. Dedicated handlers under `app/api/auth/*`
  (guest/session/login/callback/logout) take Next routing precedence; `auth/upgrade` falls through the
  catch-all. Pure token/cookie/proxy logic lives in `lib/bffSession.ts` + `lib/bffProxy.ts` (import-light,
  injectable `fetchImpl`/`env`). This is the canonical §8 `frontend/app/api/` = BFF layout.
- **Cookie**: `cc_session`, httpOnly, secure=**prod-only** (so localhost dev works), SameSite=Lax, path=/,
  Max-Age = JWT remaining lifetime. Token NEVER in localStorage/JS/URL. OIDC token reaches the browser only
  as an httpOnly cookie: backend keeps its server-to-server fragment redirect (documented not to "fix" back),
  BFF callback extracts it Node-side and issues a clean browser redirect. Client hydrates via
  `GET /api/auth/session` (token-free projection), not a URL fragment.
- **SSE passthrough**: return `backendResponse.body` verbatim, strip `content-encoding`/`content-length`/
  `transfer-encoding`. `runtime="nodejs"` required (jsdom/edge lack working streaming Request/Response).

- **FIX-05 SUPERSEDED for INTERNAL_API_URL**: [[project-docker-api-routing]] required a Docker **build ARG**
  because Next froze `rewrites()` into the build manifest. SEC-04 removed `rewrites()`; the BFF Route Handlers
  read `INTERNAL_API_URL` at **request time**, so a runtime `environment:` entry is now correct (build ARG no
  longer needed). `resolveInternalApiBaseUrl()` stays the single backend-URL source. `localhost:8000` default
  stays P11-compatible. Do NOT flag runtime-env INTERNAL_API_URL as a FIX-05 violation going forward.

- **Follow-up logged (not a blocker)**: CSP uses `script-src 'unsafe-inline' 'unsafe-eval'` (Next inline
  bootstrap) — partially undercuts the XSS rationale; tighten to nonce-based CSP later.

See [[project-security-privacy-posture]] (§6.13 ruling) and [[project-auth-session-seam]] (backend authN).
