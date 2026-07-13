---
name: check-bff-cookie-transport-tasks
description: Reviewing SEC-04-style BFF + httpOnly-cookie session-transport tasks (Next.js Route Handlers proxy /api/* to FastAPI) — cookie posture, Authorization injection, SSE passthrough, and the OAuth redirect_uri topology trap
metadata:
  type: project
---

Reviewing the Next.js **BFF** that replaces localStorage+client-Bearer with an httpOnly cookie (design §7.2/§6.13). Browser talks only to Next `:3000`; Route Handlers under `frontend/app/api/*` read the `cc_session` cookie and inject `Authorization: Bearer` server-side. Core lives in `frontend/lib/bffProxy.ts` (proxyRequest + set/clearSessionCookie) and `frontend/lib/bffSession.ts` (unverified JWT decode → token-free `clientSessionState`). Catch-all `app/api/[...path]/route.ts`; dedicated `app/api/auth/{guest,session,login/[provider],callback/[provider],logout}`.

**The load-bearing trap — OAuth redirect_uri topology (caught in rev1):**
- Backend derives the OIDC callback as `<OAUTH_REDIRECT_BASE_URL>/api/auth/callback/{provider}` (`backend/app/services/auth.py::_redirect_uri`). The **provider redirects the browser** there, so it MUST be browser-reachable. After SEC-03 removed the backend's published port, that means the **Next origin** (`localhost:3000` / the Space domain), NOT the backend (`localhost:8000`).
- Check `.env.example` + `backend/app/config.py` `OAUTH_REDIRECT_BASE_URL` default/docstring: if they still say "base URL of THIS backend" / default `:8000`, SSO breaks end-to-end in the documented local setup even though production (Space domain == frontend origin) happens to work. Flag major — an explicit acceptance criterion ("SSO login end-to-end") is then unverifiable.
- Also watch stale `OAUTH_POST_LOGIN_REDIRECT` docstring claiming the fragment is "read client-side" — the BFF now reads it server-side.

**Other checks that matter (all passed clean in rev1, so these are the bar):**
- Token never in browser: grep `frontend/` for `localStorage`/`accessToken`/`authHeaders`/`sessionFromFragment` — must be zero (comments ok); every `Bearer`/`Authorization` must be server-side (Route Handlers / bffProxy).
- `proxyRequest` must **strip** client-supplied `authorization` + `cookie` before forwarding, then set Authorization from the cookie. Verify a test asserts a forged client `Authorization` is overridden.
- Cookie posture: httpOnly, `secure` prod-only (so http://localhost dev still gets it), sameSite=lax, path=/, maxAge tracking JWT `exp`.
- JWT claim names the decoder reads (`sid`/`role`/`exp`) must match `backend/app/security/tokens.py::SessionClaims`; guest handler reads `access_token` matching `GuestSessionResponse`.
- Server-only isolation: `bffSession`/`bffProxy` (use `Buffer`/`next/server`) must be imported ONLY by Route Handlers, never client components (else browser-bundle break).
- Dockerfile ARG→runtime reversal of `INTERNAL_API_URL` is **correct here**, NOT a FIX-05 regression: the build-freeze rule is specific to `rewrites()` (frozen into the build manifest). BFF Route Handlers read env at request time (nodejs runtime), so a runtime `environment:` entry is right. Don't flag it.
- SSE: mechanism = nodejs runtime + `force-dynamic` + verbatim `ReadableStream` passthrough + strip `content-encoding`/`content-length`/`transfer-encoding`. Unit tests only prove `response.body` is a ReadableStream, NOT true incrementality; Next's outbound `compress` isn't auto-disabled for `text/event-stream` — note that live `docker compose up` SSE verification is still owed (same "only a live run catches it" lesson as [[check-frontend-next-rewrites-proxy]]).
