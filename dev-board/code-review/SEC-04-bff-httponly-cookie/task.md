# Task SEC-04-bff-httponly-cookie — BFF + httpOnly cookie session transport
- **Phase:** SEC   **Status:** ENG   **Tags:** (B/F)

## Scope
Design §6.13 / §7.2: replace the current `localStorage` + Bearer-in-JS session with a **Next.js
BFF**: an **httpOnly · Secure · SameSite=Lax** cookie holds the session, and the Next server
injects `Authorization: Bearer <token>` **server-side** on every proxied call. The token must
**never** exist in browser JavaScript and **never** appear in a URL (today the OIDC callback
puts it in the URL fragment — `backend/app/api/auth.py`'s `callback` handler — and
`frontend/lib/auth.ts` persists it in `localStorage` and attaches
`Authorization: Bearer` client-side; `frontend/next.config.ts` currently does a **transparent**
`rewrites()` passthrough of `/api/*`, which the design explicitly calls insufficient — the
browser still originates the call and still carries the token).

**Context that changes the shape of this task:** SEC-03 (already done) removed the backend's
published host port. The browser can now reach the backend **only** through the Next.js origin —
so this task isn't just "more secure", it's now load-bearing for anything to work at all from a
browser.

### Target shape (design §7.2 diagram)
```
browser ──HTTPS──▶ Next.js origin (only published port)
                      Route Handlers (BFF): httpOnly cookie → Authorization header
                      ▼ private docker network
                  FastAPI ──▶ Postgres · Redis · Celery worker
```

### What to build
1. **A BFF proxy on the Next server** that reads the session from the httpOnly cookie and
   forwards requests to the backend with `Authorization: Bearer <token>` attached
   server-side. A single catch-all Route Handler
   (`frontend/app/api/[...path]/route.ts`, methods GET/POST/PUT/DELETE/PATCH) forwarding to
   `INTERNAL_API_URL` is the pragmatic way to avoid hand-writing one handler per backend
   endpoint — reuse the existing `resolveInternalApiBaseUrl()` from `lib/apiProxy.ts`. Replace
   the current blanket `rewrites()` passthrough in `next.config.ts` with this (remove or
   narrow the rewrite so it no longer bypasses the BFF).
   - **SSE passthrough is mandatory and must survive**: `POST /api/chat` streams
     Server-Sent-Events (`frontend/lib/chatStream.ts` reads `response.body` incrementally).
     The catch-all handler must stream the backend response body straight through
     (`ReadableStream`, no buffering) with the right headers
     (`content-type: text/event-stream`, no compression/caching that breaks streaming). Use
     whatever Next.js runtime (`nodejs` is the safe default for a body-streaming proxy)
     preserves true incremental streaming — verify empirically, don't assume.
   - Auth endpoints that don't fit the generic "forward + attach Authorization" shape need
     their own handlers (still under `app/api/auth/...`, taking precedence over the catch-all
     per Next's routing rules):
     - `POST /api/auth/guest` — call the backend, receive the token payload, **set the
       httpOnly/Secure/SameSite cookie** in the Route Handler's response, and return a
       **token-free** JSON body to the client (`sessionId`, `role`, `expiresAt` — whatever the
       UI needs to render state; never `accessToken`).
     - `GET /api/auth/login/{provider}` — the browser can't reach the backend directly
       anymore, so this handler must call the backend's login endpoint **server-side** (with
       redirects **not** auto-followed) to obtain the OAuth-provider consent URL, then issue
       that redirect to the browser itself.
     - `GET /api/auth/callback/{provider}` — the provider redirects the browser here (must be
       a public Next.js route). Server-side, call the backend's callback endpoint (redirects
       not auto-followed) to complete the exchange and obtain the session token — the
       backend's existing "token in a redirect fragment" response is fine to *keep
       server-side* (only the Next.js Node process ever sees that Location header now; it
       never reaches the browser), or change the backend to return the token as JSON directly
       if that's cleaner — engineer's call, but the **browser-visible response** from this
       handler must be a clean redirect (e.g. to `/`) with **no token in the URL**, plus the
       httpOnly cookie set on that redirect response.
     - `POST /api/auth/logout` — clear the cookie(s) here; best-effort forward to the backend
       to revoke server-side.
     - `POST /api/auth/upgrade` — fine to fall through the generic catch-all (it just needs
       the Authorization header attached, no special cookie handling), but double check its
       response.
   - Add a small `GET /api/auth/session` Route Handler that reads the cookie(s) and returns
     the client-safe session state (`sessionId`, `role`, `expiresAt`, `isAuthenticated`) with
     no token — used to hydrate UI state on page load / refresh instead of localStorage.
   - A reasonable pattern: split the cookie into (a) the httpOnly token cookie (never read by
     JS) and (b) a small non-httpOnly, **token-free** metadata cookie or rely purely on the
     `/api/auth/session` handler for hydration — pick one, document the choice in
     `engineer.md`.

2. **Backend OIDC callback** (`backend/app/api/auth.py`) — only touch if you decide to change
   its response shape (see above). If you keep the redirect-with-fragment shape because it's
   now server-to-server-only, add a comment there explaining *why* it's still safe (only the
   BFF's Node process ever follows that redirect, not a browser) so a future reader doesn't
   "fix" it back into an XSS-exposed pattern.

3. **Frontend client rewrite** (`frontend/lib/auth.ts`, `frontend/lib/chatStream.ts`,
   `frontend/lib/profile.ts`, `frontend/components/Chat.tsx`, `frontend/app/auth/callback/page.tsx`,
   and their tests):
   - Stop persisting any token in `localStorage`; stop building `Authorization` headers
     client-side (`authHeaders()` becomes unnecessary now that the BFF injects the header —
     remove it or repurpose it strictly for tests).
   - Requests rely on the browser sending the httpOnly cookie automatically on same-origin
     fetches (`credentials: "same-origin"`, the fetch default) — no client code touches the
     token at all.
   - `sessionFromFragment` / the `/auth/callback` page's job changes: since the callback is
     now a server-side redirect that lands the browser on a clean URL with the cookie already
     set, the client no longer needs to parse a URL fragment for the token. Update/replace
     this page to just call `GET /api/auth/session` (or read whatever hydration mechanism you
     picked) to refresh UI state, then navigate to the app.
   - Keep the guest-session / SSO-login / upgrade / logout **flows** working end-to-end from
     the user's point of view — only the transport changes.

4. **Security headers / CSP** on the Next origin (design §7.2 "Security headers / CSP... CORS
   remains closed"). Add baseline security headers (e.g. via `next.config.ts` `headers()` or
   middleware): `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` (or
   `frame-ancestors 'none'` via CSP), a reasonable `Content-Security-Policy` for a same-origin
   SPA, and confirm CORS is not opened anywhere (no `Access-Control-Allow-Origin: *` on the
   backend or the BFF).

## Acceptance criteria
- [ ] The session token never appears in `localStorage`, any other client-readable storage, or
      any URL (query string or fragment) visible to the browser.
- [ ] `Authorization` header is attached to backend calls **only** by the Next.js server (BFF),
      never by client JS.
- [ ] Cookie is `httpOnly`, `Secure` (in production), `SameSite=Lax`.
- [ ] Guest session creation, SSO login (both providers), guest→account upgrade, and logout all
      work end-to-end through the browser.
- [ ] `POST /api/chat` SSE streaming still delivers tokens incrementally through the BFF (not
      buffered into one chunk) — verify with a manual/integration check.
- [ ] Baseline security headers present on the Next origin; CORS stays closed.
- [ ] Existing frontend tests updated to match the new contract; new tests cover the Route
      Handlers (cookie set/cleared, Authorization injected, no token in response body for
      `/api/auth/guest` and `/api/auth/session`).

## Design references
- dev-board/app-design-and-features.md §7.2 "Network posture & session transport", §6.13.
- dev-board/tasks.md — SEC block, item **S4**. Note: **S13 (consent gate) is a separate,
  follow-up task** that will extend the guest/login session-creation handlers you're writing
  here — don't implement consent logic now, but avoid making the handlers so rigid that adding
  a "has the user accepted ToS?" check later requires a rewrite.

## Constraints / non-goals
- Do not implement the consent gate (S13/SEC-06) or the GDPR erasure/export endpoints
  (S6/SEC-05) here — session transport only.
- Do not change AuthN/AuthZ logic on the backend beyond what's needed for the callback response
  shape decision above — `SessionAuthenticator`, JWT validation, etc. stay as-is.
- Keep `INTERNAL_API_URL` / `resolveInternalApiBaseUrl()` as the single source of truth for the
  backend origin (per the FIX-05 lesson already documented in `lib/apiProxy.ts`) — don't
  hardcode a second backend URL resolution path.
