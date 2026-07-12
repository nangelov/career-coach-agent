---
name: project-job-status-capability-authz
description: GET /api/jobs/status/{task_id} uses a capability (not ownership) authz model returning PII from a UUID-scoped URL — the residual risk to re-check when P6 reuses it
metadata:
  type: project
---

`GET /api/jobs/status/{task_id}` (P5-06, `app/api/jobs.py` + `app/services/jobs.py`) is
`require_auth` but **not ownership-checked**: the Celery UUID4 `task_id` is treated as a bearer
capability. On `SUCCESS` it returns the full parsed-profile PII payload.

**Why it was accepted (do not re-gate the P5 form):** `task.md` explicitly pre-sanctioned either
model; UUID4 entropy + result-backend TTL bound the risk; and a guest's CV preview has no
persisted profile, so it *must* come back through the poll result — ownership-only would break
the guest flow.

**How to apply — what to check when this endpoint is touched or reused (P6 crawl/OCR jobs share
it):**
- The common false justification for the capability model is "guests have no `user_id` to key
  ownership on." Not true: both guests and users always carry `CurrentUser.session_id`, and the
  enqueue path already receives `session_id`. Ownership *is* uniformly keyable on `session_id`
  (cheap Redis `job:{task_id}->session_id` with TTL). So the honest argument is YAGNI/KISS cost,
  not infeasibility — hold authors to that.
- Capability-in-URL leaks via access logs, browser history, `Referer`, and analytics (v1 wired
  `gtag`). Flag if a `task_id`-bearing URL could reach analytics/third parties.
- When a *new* producer's result is more sensitive or cross-tenant than a self-uploaded CV,
  push to reconsider ownership scoping rather than inheriting the capability model by default.
- Always confirm the `FAILURE`/`REVOKED` paths return the generic message and never the Celery
  exception object, and that `isinstance(info, dict)` guards keep a `RETRY`-state exception out
  of `stage`/`message`/`result`.
