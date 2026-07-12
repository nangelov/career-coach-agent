---
name: check-frontend-profile-poll-tasks
description: Reviewing P5-07+ frontend CV-upload / async-job-polling tasks (lib/profile.ts + CvUpload/ProfileView) — wire-type vs backend-schema parity, poll robustness, error-status coverage
metadata:
  type: project
---

Reviewing the frontend profile/CV-upload surface (`frontend/lib/profile.ts`, `components/CvUpload.tsx`,
`components/ProfileView.tsx`, `app/profile/page.tsx`) and any later frontend that polls async Celery jobs.

**Why:** this layer mirrors the wire contract by hand (snake_case TS types), so drift from the backend
Pydantic schemas is the highest-value class of bug to catch; and interval polling is easy to get subtly
wrong (infinite loops, unaborted timers).

**How to apply — check every time:**
- **Wire parity:** cross-read the TS types against `backend/app/ingestion/profile.py::ProfileSchema`,
  `backend/app/schemas/jobs.py::JobStatusResponse`, `backend/app/schemas/profile.py::CvUploadResponse`.
  Fields must match field-for-field (snake_case kept so `GET`→edit→`PUT` round-trips losslessly).
- **Error-status coverage:** the frontend must branch on the exact 4xx the router raises — confirm against
  `backend/app/api/profile.py` (401/403 guest-PUT/413/415/429/422/400) and the guest contracts
  (`GET /api/profile` returns 200-empty not 404 for guest/fresh; `PUT` is 403 for guests). Fallback messages
  should be user-safe, prefer backend `detail`.
- **Poll robustness:** an interval poller (`pollJobUntilTerminal`-style) should be cancellable (AbortSignal,
  cleared timers, no fetch after abort) AND ideally bounded — Celery reports an unknown/expired `task_id` as
  `PENDING` forever, so an unbounded loop = spinner-forever + endless traffic. Flag missing upper bound as
  minor (robustness), not a blocker if abort-on-unmount exists.
- **Conventions to expect (mirror, don't reinvent):** injectable `fetchImpl`/`baseUrl` DI, `authHeaders(session)`
  bearer attach, defensive wire→type mappers, best-effort `readDetail` for `{detail}`. Multipart upload must
  NOT set `Content-Type` (browser sets the boundary).
- **XSS:** parsed-CV content rendered as React text is auto-escaped — fine; only flag if it ever hits
  `dangerouslySetInnerHTML`.
- Reproduce `npm run lint && npm run build && npm test` — cheap and authoritative here.
