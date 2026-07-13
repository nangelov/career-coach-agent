# Task SEC-10-container-verify — Confirm tests pass + live-container check for the SEC block
- **Phase:** SEC   **Status:** ENG   **Tags:** (T)

## Scope
The SEC block (SEC-01..SEC-09, items S1/S2/S5/S4/S6/S13/privacy-ToS/S10) was just completed.
SEC-09's verification pass ran the backend/frontend test suites but — per its own code-review
notes — leaned on the engineer's report for some suites and did **not** confirm a live
`docker compose up` of the full 5-service stack after the SEC-03 port lockdown + SEC-04 BFF
rework, which are exactly the two changes most likely to break the stack's actual boot/runtime
behavior (compose file structure changed, Next.js now proxies via real Route Handlers instead of
a blanket rewrite). Docker is available in this sandbox — use it.

Do this now, in order:

1. **Run the full backend test suite fresh** (`cd backend && <the project's real pytest
   invocation — check Makefile/CI workflow for the exact command>`), and the **full frontend
   test suite fresh** (`cd frontend && npm test -- --watchAll=false` or whatever the project's
   real non-interactive command is). Capture pass/fail counts. If anything fails, fix the root
   cause (code or test) and re-run until green — do not report done with red tests.
2. **Bring up the real container stack**: `docker compose up --build -d` from the repo root
   (this exercises the SEC-03 port-lockdown compose file and the SEC-04 BFF Dockerfile/ARG
   wiring for real, not just via unit tests). Confirm:
   - All 5 services reach a healthy/running state (`docker compose ps`).
   - `curl localhost:3000` (the only published port) succeeds.
   - `curl localhost:8000` and `curl localhost:5432`/`6379` (host) **fail to connect** —
     confirming the SEC-03 port lockdown is real, not just present in the YAML.
   - Through the frontend origin: `POST /api/auth/guest` (with consent per SEC-06) returns a
     **token-free** JSON body and sets an httpOnly cookie (`curl -i` and inspect `Set-Cookie` —
     confirm `HttpOnly` flag present, no `access_token`/similar in the response body).
   - A basic authenticated call through the BFF (e.g. `GET /api/auth/session` using the cookie
     just obtained) succeeds, confirming the Route Handler is genuinely injecting
     `Authorization` server-side against the live backend, not just in unit tests with a mocked
     fetch.
   - If reasonably feasible in this sandbox (no real OAuth provider creds needed): a quick
     `POST /api/chat` call through the frontend origin streams SSE tokens end-to-end against the
     live backend (may require a guest session + whatever minimal setup the chat endpoint
     needs — use what's actually available, e.g. a stub/dummy LLM config if the real HF token
     isn't present in this sandbox; if a full live LLM call truly isn't possible here, document
     exactly why and fall back to confirming the SSE plumbing up to the point it would call the
     model).
   - `docker compose down` cleanly afterward (don't leave the stack running / volumes dangling
     unexpectedly — match the P2 precedent of `docker compose down` to tear back down).
3. **Report exactly what was and wasn't possible to verify live** (e.g. if the sandbox lacks
   real Google/LinkedIn OAuth secrets or a real HF inference token, say so plainly rather than
   silently skipping) — the design's own honesty standard (§6.17) applies to how you report
   test coverage too.

## Acceptance criteria
- [ ] Backend test suite run fresh, green (or fixed to green).
- [ ] Frontend test suite run fresh, green (or fixed to green).
- [ ] `docker compose up --build` succeeds; all 5 services healthy.
- [ ] Confirmed live: only port 3000 reachable from the host; 8000/5432/6379 are not.
- [ ] Confirmed live: guest-session cookie is httpOnly and token-free in the response body.
- [ ] Confirmed live (or explicitly documented as not possible in this sandbox, with why): an
      authenticated BFF call succeeds against the real backend.
- [ ] `docker compose down` run at the end; no leftover state causing problems for future runs.
- [ ] Any real defect found while doing this (not just theoretical) is fixed, small and
      targeted — this is a verification task, not a rewrite.

## Design references
- dev-board/app-design-and-features.md §7.2 (port lockdown, BFF), §6.13, §6.22 (consent).
- dev-board/code-review/SEC-03-port-lockdown/, SEC-04-bff-httponly-cookie/,
  SEC-06-consent-gate/, SEC-09-verify/ — prior task context.

## Constraints / non-goals
- Do not re-verify SEC-05/SEC-08's claims that already had live-DB or router-level proof per
  their own review files — focus this pass on what SEC-09 could **not** fully confirm: the real
  container boot + BFF-against-real-backend behavior.
- Do not implement new features. Fix only genuine defects surfaced by this live check.
