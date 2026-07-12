---
name: project-upload-endpoint-size-guard
description: On any multipart file-upload endpoint (POST /api/profile/cv and later doc/CV uploads), verify the size cap is enforced BEFORE the body is read into memory — a post-read length check is a false guard / memory-DoS
metadata:
  type: project
---

v2 file-upload endpoints (FastAPI `UploadFile`, e.g. `app/api/profile.py::upload_cv`) must cap size **before** materializing the body.

**Why:** the codebase has a `CV_UPLOAD_MAX_BYTES` setting, but P5-04 rev1 enforced it only inside the service *after* `content = await file.read()` — which already pulls the whole (disk-spooled) multipart part into a single `bytes`. Starlette (1.3.x here) sets **no** default total-request-body limit, and `main.py` has no body-size middleware (only CORS/GZip/RequestID). So one authenticated request with a multi-GB file exhausts disk (spool) then RAM (read) → OOM. Guest tokens are self-serve (`POST /api/auth/guest`), and the rate-limit gate is checked *after* the read on the first request, so the cap doesn't actually bound memory. Flagged `major` (C1).

**How to apply, for every upload route:**
- Reject on `file.size` (Starlette populates it during parse) before `await file.read()`, and/or read in bounded chunks up to the cap. A length check on already-read `content` is not sufficient on its own.
- Watch the **order** of the rate-limit gate vs. validation: charging the budget before validating means a rejected upload (415/413/400) still consumes it — and a guest has exactly 1 upload (`GUEST_MAX_UPLOADS=1`), so a wrong file permanently locks them out that session. Prefer validate-then-charge (P5-04 C2, `minor`).
- Also check worker-side resource construction in the Celery entrypoint builds collaborators inside the `try` guarded by the closing `finally` (else a redis/PG client built before the `try` leaks on a later constructor error — P5-04 C3, nit). See [[project-chat-llm-review-checks]] for the lazy-DI/pool posture.
