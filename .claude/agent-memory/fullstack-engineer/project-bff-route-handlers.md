---
name: bff-route-handlers
description: Next.js BFF (httpOnly cookie → server-side Authorization) — structure, streaming proxy, and how to unit-test Route Handlers under jest
metadata:
  type: project
---

SEC-04 replaced the transparent `next.config.ts` `rewrites()` /api passthrough with a **BFF**:
Route Handlers under `frontend/app/api/*` that read the session JWT from an **httpOnly ·
Secure(prod) · SameSite=Lax** cookie (`cc_session`) and inject `Authorization: Bearer` when
forwarding to the backend. The token never exists in browser JS.

**Layout & conventions:**
- Pure token helpers (no `next/server`) → `lib/bffSession.ts`: `SESSION_COOKIE`,
  `decodeSessionToken` (base64url payload, *unverified* — display only; backend re-verifies),
  `clientSessionState` (token-free `{isAuthenticated,sessionId,role,expiresAt}`).
- Server proxy + cookie set/clear → `lib/bffProxy.ts`: `proxyRequest(request, {fetchImpl,env})`.
- `resolveInternalApiBaseUrl` (in `lib/apiProxy.ts`) stays the single backend-origin resolver;
  the BFF reads `INTERNAL_API_URL` at **request time** (not build), so docker-compose passes it
  as a runtime `environment:` entry, NOT a build ARG (reverses the old FIX-05 build-freeze note).
- Catch-all `app/api/[...path]/route.ts` (`export { handle as GET, ... }`) forwards everything;
  more-specific `app/api/auth/*` handlers take precedence. `auth/upgrade` falls through the
  catch-all fine. Set `export const runtime = "nodejs"` + `dynamic = "force-dynamic"`.
- **SSE streaming**: return `new NextResponse(backendResponse.body, {...})` (the undici
  `ReadableStream`) directly — never `await .text()`. Strip `content-encoding`/`content-length`/
  `transfer-encoding` from the response; strip `cookie` + client `authorization` from the request;
  for non-GET/HEAD forward `request.body` with `duplex: "half"`.

**Testing Route Handlers under jest (this is the tricky part):**
- Add `/** @jest-environment node */` at the top of the test file. jsdom lacks a working
  `Request`/`Response`/`ReadableStream`/`fetch`; the **node** env gives Node 18+ undici globals so
  `next/server` `NextRequest`/`NextResponse` work.
- Construct `new NextRequest("http://localhost:3000/api/...", { headers: { cookie: "cc_session=..." }, method, body })`.
- Mock backend calls with `jest.spyOn(global,"fetch")` returning real `new Response(...)`; or inject
  `fetchImpl` into `proxyRequest`.
- Next 15 handler `params` is a **Promise** — pass `{ params: Promise.resolve({ provider: "google" }) }`.
- Bracket-dir imports work: `import { GET } from "@/app/api/auth/login/[provider]/route"`.
- Do NOT put shared `.ts` helpers inside `__tests__/` — next/jest testMatch globs every file there
  and fails it as an empty suite. Inline helpers per test file.
- The token-free contract is testable: assert `JSON.stringify(body).not.toContain(token)` for the
  `/api/auth/guest` + `/api/auth/session` bodies, and `response.cookies.get("cc_session")` for the
  cookie.
