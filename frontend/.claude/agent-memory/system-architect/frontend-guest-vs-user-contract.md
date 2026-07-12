---
name: frontend-guest-vs-user-contract
description: Guest-vs-user backend contract the frontend must surface — 200-empty profile, 403 guest PUT, 429 upload cap
metadata:
  type: project
---

Backend profile/rate-limit contract the frontend must honor (design §4/§7, backend
`api/profile.py`, `api/jobs.py`): `GET /api/profile` returns a **200 empty ProfileSchema**
(never 404) for fresh accounts and guests, so a view/edit UI always renders; `PUT /api/profile`
is **403 for guests** (a profile is anchored to a `users` row); guest CV upload is capped
(P3-04, **429** on the 2nd). A Celery `task_id` is an unguessable capability — `GET
/api/jobs/status/{task_id}` requires auth but does not check enqueuer ownership, so a guest
polls their own job with the token they hold.

**Why:** guests are Redis-only with harder limits (§4/§6.8); these distinct states must read as
clear prompts, not raw HTTP errors.

**How to apply:** APPROVE frontend that branches on typed status-carrying errors for
401/403/413/415/429 with friendly messages and treats empty-200 as "no profile yet"; flag UIs
that treat guest 403/429 as a generic failure or expect a 404 for the empty profile.
See [[frontend-lib-components-layering]].
