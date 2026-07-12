---
name: ruling-job-status-capability-authz
description: GET /api/jobs/status/{task_id} may use capability (unguessable task_id) authZ in P5, but the §7 own-data ownership map is a live P6 follow-up
metadata:
  type: project
---

`GET /api/jobs/status/{task_id}` (P5-06) authorizes with a **capability model**: `require_auth` gates
(no anonymous poll) but there is **no task-ownership check** — the Celery UUID4 `task_id` is treated as an
unguessable bearer capability. Blessed at P5 rev 1 as APPROVED-with-follow-up.

**Why blessed:** task_id is high-entropy UUID4 handed back only to the enqueuer; result backend expires;
the P5-06 task brief *explicitly pre-authorized either choice*; tightening is cheap & purely additive
(Redis `SETEX job_owner:{task_id} <ttl> <session_id>` at enqueue + `current_user.session_id` check at poll)
with **no wire/schema/seam change** — so it fails my "expensive to unwind" gate threshold, hence not
CHANGES_REQUESTED.

**Why it's still a live gap vs. §7** ("users access only their own data"): the result carries full profile
PII, the codebase already has a centralized own-data primitive (`security/dependencies.py::
authorize_session_access`) this endpoint deliberately skips, and the `task_id` rides in the **URL path**
(capability-URL leakage via logs/history/Referer).

**How to apply:** This endpoint is generic and P6 crawl/OCR producers reuse it — broadening exposed result
types. **At P6, require the additive `task_id → session_id` Redis ownership map** (or equivalent) before
re-approving; do **not** silently re-bless capability-only when P6 touches this endpoint. Pattern mirrors the
cheap-to-tighten / logged-follow-up posture in [[ruling-client-history-trust]].
