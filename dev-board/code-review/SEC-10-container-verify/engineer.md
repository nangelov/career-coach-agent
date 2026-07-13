# Engineer report — SEC-10-container-verify · Revision 1

## Summary
Verification-only task. Ran both test suites fresh (green), then brought up the real 5-service
`docker compose` stack and confirmed live: the SEC-03 port lockdown (only :3000 reachable),
the SEC-04 BFF httpOnly-cookie flow (token-free guest body + server-side `Authorization`
injection against the **real** backend), the SEC-06 consent gate, and the SSE chat pipeline
end-to-end up to the model-call boundary. Tore the stack down cleanly. **No code changes were
needed — no genuine defect surfaced.**

## Files changed
- None. This is a live-verification pass; nothing in the codebase required a fix.

## Key decisions
- Used the project's real commands: backend `uv run --no-sync pytest` (per `backend/Makefile`
  `test` target / backend-ci.yml), frontend `npm test -- --watchAll=false` (per frontend-ci.yml).
- Proved server-side `Authorization` injection with `GET /api/profile` (routes through the
  **catch-all** BFF proxy `app/api/[...path]/route.ts` → live backend), not `GET /api/auth/session`
  — the session handler only decodes the cookie locally and never calls the backend, so it alone
  would not prove the "inject against real backend" claim (design §7.2).
- Left named volumes in place after `docker compose down` (no `-v`), matching the P2 precedent
  documented in `backend/Makefile` `test-integration-full`.

## How to verify (exact commands + results)

### 1. Backend suite (fresh, final run)
`cd backend && uv run --no-sync pytest -q`
→ **495 passed, 54 skipped** (~9s). The 54 skips are the live-DB integration tests that skip when
no Postgres is reachable at `DATABASE_URL` on the host — same as CI without the service container.

### 2. Frontend suite (fresh, final run)
`cd frontend && npm test -- --watchAll=false`
→ **14 suites / 135 tests passed**.

### 3. Stack up
`docker compose up --build -d` → all images built, all containers started (exit 0).
`docker compose ps` after ~25s:
- `backend` Up (healthy), PORTS `8000/tcp` (not published)
- `db` (pgvector/pgvector:pg16) Up (healthy), PORTS `5432/tcp` (not published)
- `redis` Up (healthy), PORTS `6379/tcp` (not published)
- `worker` Up, PORTS `8000/tcp` (no healthcheck defined → shows plain "Up")
- `frontend` Up, PORTS `0.0.0.0:3000->3000/tcp` (the ONLY published host port)

### 4. Port lockdown (SEC-03) — confirmed live
- `curl localhost:3000` → **HTTP 200** (reachable).
- `curl localhost:8000` → connection refused (HTTP 000).
- TCP connect `localhost:5432` → **Connection refused**.
- TCP connect `localhost:6379` → **Connection refused**.
Only :3000 is reachable from the host; backend/db/redis are internal-network-only.

### 5. Guest session (SEC-04 + SEC-06) — confirmed live
`POST http://localhost:3000/api/auth/guest -d '{"consent":true}'`:
- **HTTP 200**, body **token-free**: `{"sessionId":"...","role":"guest","expiresAt":...}` — no
  `access_token`/JWT in the body.
- `Set-Cookie: cc_session=<jwt>; Path=/; Max-Age=3600; Secure; HttpOnly; SameSite=lax` — **HttpOnly
  present**. Cookie jar records it with the `#HttpOnly_` prefix.
- Consent gate: `POST /api/auth/guest -d '{"consent":false}'` → **HTTP 400** (backend rejects a
  guest start without consent, per §6.22).

### 6. Authenticated BFF call against the real backend (SEC-04) — confirmed live
Through the catch-all proxy with the guest cookie:
- `GET /api/profile` **with** cookie → **HTTP 200** `{"skills":[],"experience":[],"education":[],"goals":[]}`
  (real backend response for a fresh guest).
- `GET /api/profile` **without** cookie → **HTTP 401** (backend enforces auth; the proxy injects
  `Authorization` only when the httpOnly cookie is present). This proves the Route Handler injects
  the bearer server-side against the live backend, not via a mocked fetch.
- (`GET /api/auth/session` with cookie → `{"isAuthenticated":true,...}`, token-free — the local
  cookie-decode hydration path; noted separately from the backend-hitting proof above.)

### 7. SSE chat plumbing (design §7.2) — partially verified (see limitation)
`POST http://localhost:3000/api/chat` (guest cookie, `session_id` = the guest sid) →
**HTTP 200, content-type `text/event-stream`**, streamed frames end-to-end through the BFF:
```
event: start  → {"message_id": "..."}
event: plan   → {"intent":"chat","steps":[...],"workers":[]}
event: token  → {"content":"I'm sorry — I'm having trouble generating a response right now..."}
event: done   → {"message_id":"...","finish_reason":"error","citations":[]}
```
The full pipeline (BFF Route Handler → catch-all proxy with injected auth → live backend →
LangGraph → SSE frames → streamed back through the :3000 origin) works. The **actual LLM token
generation could not run in this sandbox** — see limitations.

### 8. Teardown
`docker compose down` → all containers/network removed cleanly; `docker compose ps` empty. Named
volumes `career-coach-agent_postgres_data` / `_redis_data` intentionally preserved (no `-v`, P2
precedent).

## What could NOT be verified live in this sandbox (and why)
- **Real LLM token generation.** Backend logs show the failover router tried both models and both
  hit `httpcore.ConnectError: [Errno -5] No address associated with hostname` →
  `openai.APIConnectionError` → `LLMAllModelsFailedError`. The sandbox has **no outbound DNS/network
  egress** to the HF Inference Provider host, so the model call cannot complete regardless of token
  validity. This is an environment limitation, **not a code defect** — and the observed behavior is
  exactly the designed guardrail: the service never raises into the stream; it emits a graceful
  fallback `token` + an `error` `done` event so the SSE stream always ends cleanly. SSE plumbing is
  therefore verified up to (and including) the point where it invokes the model.
- **Real Google/LinkedIn OAuth login callback.** No real OIDC provider secrets are available in this
  sandbox, so the SSO login/callback path was not exercised end-to-end (out of this task's scope;
  the guest + BFF-auth paths that SEC-10 targets were fully covered).

## Tests (final step — mandatory)
- `cd backend && uv run --no-sync pytest -q` → **495 passed, 54 skipped** (fresh final run).
- `cd frontend && npm test -- --watchAll=false` → **135 passed, 14 suites** (fresh final run).
- No failures; no root-cause fixes required (no code changed).

## Self-check
- [x] Meets acceptance criteria: both suites green; stack up with all 5 services; port lockdown
      confirmed live (only :3000); guest cookie httpOnly + token-free body; authenticated BFF call
      succeeds against the real backend (401 without cookie); `docker compose down` run; SSE verified
      up to the model boundary (real LLM call documented as sandbox-impossible with the reason).
- [x] No secrets committed; no code touched (Router→Service→Agent/Repo layering untouched).
- [x] Tests/lints pass (pasted above).
