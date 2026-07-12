# Task FIX-05-docker-frontend-api-routing — Frontend cannot reach the backend under docker-compose
- **Phase:** cross-cutting   **Status:** ENG   **Tags:** (I) (F)

## Scope
**User-reported bug, reproduced live.** Running the full stack via `docker compose up --build` and opening
`http://localhost:3000`: clicking "Continue as guest" (and "Continue with Google") fails. DevTools shows:

```
POST http://localhost:3000/api/auth/guest → 404 Not Found
Response headers: X-Powered-By: Next.js, X-Nextjs-Cache: HIT
```

**Root cause (confirmed):** every frontend API call (`frontend/lib/auth.ts`, `lib/chatStream.ts`,
`lib/profile.ts`) hits a same-origin path (`${baseUrl}/api/...` with `baseUrl` defaulting to `""`), relying
entirely on the Next.js dev-server `rewrites()` proxy defined in `frontend/next.config.ts`:

```ts
async rewrites() {
  if (process.env.NODE_ENV !== "development") {
    return [];
  }
  return [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }];
}
```

That rewrite is **deliberately disabled** outside `next dev` (comment: *"In production the reverse proxy /
single-container Dockerfile handles routing"*). The `frontend` Dockerfile runs `next start` (production mode,
`NODE_ENV=production`), so the rewrite returns `[]`. `docker-compose.yml` runs `frontend` (port 3000) and
`backend` (port 8000) as two **separate** containers/origins with **no reverse proxy** in front of either —
so in the docker-compose deployment, `/api/*` calls from the browser have nowhere to go and 404 inside the
Next.js server itself. This breaks **guest auth, SSO auth, chat, and CV/profile** — every feature — whenever
the app is run via `docker compose up`, which is the primary way this repo documents running it locally.

## Fix it
Pick (and clearly justify) one approach, keeping in mind: (a) `next dev` must keep working exactly as today
(no regression to the existing dev workflow / existing frontend tests), (b) the eventual HF Spaces
single-container deployment (P11) is explicitly a *different* routing story per the existing code comment —
don't paint that phase into a corner, but don't scope-creep into implementing it now either, (c) prefer to
avoid CORS if a same-origin proxy is a clean fit, matching this codebase's stated preference
("avoid CORS and hard-coded hosts" — see the `next.config.ts` comment), but a CORS-based cross-origin
approach (backend `ALLOWED_ORIGINS` already exists in `backend/app/config.py`, defaulting to
`["http://localhost:3000"]`) is acceptable if better justified. Two concrete options to weigh:

1. **Always-on, configurable rewrite proxy.** Remove the `NODE_ENV !== "development"` guard so the Next.js
   server-side rewrite runs in production too, with the destination host parameterized by an env var
   (e.g. `INTERNAL_API_URL`, defaulting to `http://localhost:8000` to preserve today's bare `next start`
   behavior) instead of the hard-coded `http://localhost:8000`. Wire `docker-compose.yml`'s `frontend`
   service to set `INTERNAL_API_URL=http://backend:8000` (the compose service DNS name — reachable from the
   frontend container's Node process, which is what actually executes `rewrites()`, even though the browser
   itself only ever talks to `:3000`). No CORS needed; the browser origin never changes.
2. **Configurable base URL + CORS.** Add a `NEXT_PUBLIC_API_BASE_URL` (or similar) build-time env var,
   thread it through as the default `baseUrl` in `lib/auth.ts`/`lib/chatStream.ts`/`lib/profile.ts` (and the
   components that call them without an explicit `baseUrl` today), set it at Docker **build** time (Next.js
   inlines `NEXT_PUBLIC_*` vars into the client bundle at build, not at container runtime — a plain
   `environment:` on the compose service is *not* enough; needs a Dockerfile `ARG`/`ENV` + `docker-compose`
   `build.args`) to `http://localhost:8000` for docker-compose, and ensure `backend/app/config.py`'s
   `ALLOWED_ORIGINS` covers the browser's actual origin.

Whichever you choose, also:
- Verify (don't just assert) the fix by actually bringing up `docker compose up --build` in this
  environment, exercising guest login end-to-end (`POST /api/auth/guest` → 200, session stored, chat page
  reachable) through the real browser flow or an equivalent scripted HTTP check against the running
  containers, and pasting the evidence in your report. This bug was only caught by a live run, not by any
  existing test — a "tests pass" report alone is not sufficient sign-off here.
- Check whether SSO (Google/LinkedIn) redirect/callback URLs (`OAUTH_REDIRECT_BASE_URL`,
  `OAUTH_POST_LOGIN_REDIRECT` in `.env.example`) still make sense with whichever fix you choose (they're
  already `http://localhost:8000` / `http://localhost:3000` respectively — confirm no change needed, or
  make one if your approach requires it).
- Update `.env.example` / `docker-compose.yml` comments if you add or repurpose any env var, so the next
  person running `docker compose up` doesn't hit this again.
- **Add an automated regression test — this is mandatory, not optional.** A frontend test asserting the
  resolved API base/rewrite config in a simulated "production" (`NODE_ENV=production`) build context, so this
  class of regression (every `/api/*` call silently going nowhere outside `next dev`) is caught by `npm test`
  without requiring a manual docker run next time. If a pure unit-level assertion isn't a good fit for your
  chosen approach, add whatever automated check *is* a good fit (e.g. a backend/integration script the CI
  could run) — but ship *some* automated coverage, not manual verification alone.
- **Check *every* frontend-consumed endpoint, not just guest auth, against the live docker-compose stack.**
  This bug affects the whole `/api/*` surface identically (it's a routing-layer bug, not an auth-specific
  one), so verify at minimum: `POST /api/auth/guest` (guest login), `POST /api/chat` (a real streamed chat
  turn, SSE), `POST /api/profile/cv` + `GET /api/jobs/status/{task_id}` (CV upload + poll), `GET /api/profile`
  (profile read). Paste evidence (status codes / response bodies / SSE frames observed) for each, not just
  guest auth — a fix verified against one endpoint but silently broken for another is not acceptable sign-off.

## Acceptance criteria
- [ ] `docker compose up --build` from a clean checkout, then opening `http://localhost:3000` and clicking
      "Continue as guest", successfully creates a session (no 404, no CORS error) and lands on the chat page.
- [ ] SSO login (`Continue with Google`) at least reaches the real Google OAuth consent redirect (full SSO
      completion isn't testable without real Google credentials in this environment, but the request must no
      longer 404 against the frontend itself).
- [ ] `npm run dev` (existing local dev workflow, outside Docker) still works unchanged — no regression.
- [ ] Chat and CV-upload/profile flows (which hit the same `/api/*` surface) are implicitly fixed by the same
      change — spot-check at least one (e.g. a guest chat message round-trips) in your live verification.
- [ ] `ruff`/`mypy`/backend `pytest` and frontend `lint`/`build`/`jest` all still pass.
- [ ] Report includes the actual `docker compose up` verification evidence (curl/browser network log/log
      excerpt showing `/api/auth/guest` resolving to the backend and returning `200`), not just a description
      of the fix.

## Design references
- `frontend/next.config.ts` — the existing rewrite + its explicit "production = reverse proxy / single
  container handles it" comment (the assumption this bug falls through).
- `docker-compose.yml` — the two-container (frontend `:3000` / backend `:8000`), no-reverse-proxy topology.
- `frontend/Dockerfile` — `next start` production server (no rewrite).
- `backend/app/config.py::ALLOWED_ORIGINS`, `backend/app/main.py` (`CORSMiddleware` wiring) — already present
  if the CORS route is chosen.
- `frontend/lib/auth.ts`, `lib/chatStream.ts`, `lib/profile.ts` — the `baseUrl` DI seam every API call already
  goes through (mirror/extend this, don't invent a parallel mechanism).
- dev-board/app-design-and-features.md §9 (API surface), §11 (deploy) — P11 is where the eventual HF Spaces
  single-container routing gets finalized; this fix is scoped to making local `docker-compose` usable now,
  not to pre-empting P11.

## Constraints / non-goals
- Do not implement the HF Spaces single-container deploy story here — that's P11. This fix only needs to make
  `docker compose up` (the repo's documented local multi-container setup) actually work end-to-end.
- Do not silently swap in a different auth/session mechanism — the bug is routing, not the auth logic itself
  (P3's guest/SSO implementation is not in question).
- Keep the existing `npm run dev` proxy-based workflow working unchanged.
