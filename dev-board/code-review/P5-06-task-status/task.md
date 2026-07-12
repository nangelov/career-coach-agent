# Task P5-06-task-status — GET /api/jobs/status/{task_id}
- **Phase:** P5   **Status:** ENG   **Tags:** (B)

## Scope
tasks.md item: "`GET /api/jobs/status/{task_id}` — poll async task progress."

This is the consumer side of `P5-04-cv-upload-endpoint`'s Celery task (`app/tasks/profile_ingest.py::ingest_cv`,
`task_id` returned by `POST /api/profile/cv`). Add a generic **job status polling** endpoint (design §8 API
table line 402: "Poll async job (OCR/crawl) progress | new (Celery)" — the wording is deliberately generic
because P6's crawl tasks will reuse the same endpoint later, so keep this generic to Celery task ids, not
CV-specific).

- `GET /api/jobs/status/{task_id}` — looks up the Celery task's current state via the existing
  `celery_app` (Redis-backed result backend, already configured in `app/tasks/celery_app.py`) using
  `AsyncResult(task_id, app=celery_app)`, and returns a typed response with at least: `task_id`, `status`
  (map Celery's `PENDING`/`STARTED`/`PROGRESS`(custom `PARSING`/`STRUCTURING`/`PERSISTING`)/`SUCCESS`/`FAILURE`
  states to a stable API-level enum/string set), `progress`/`stage` info (whatever `meta` the P5-04 task's
  `self.update_state(..., meta=...)` calls attached), and — on `SUCCESS` — the task's result payload (the
  `{profile, persisted, kb_document_id, chunk_count}` shape P5-04 documented as "P5-06-consumable"), or — on
  `FAILURE` — a client-safe error message (do not leak internal tracebacks).
- **AuthZ.** This app's locked decision is "users access only their own data" (§7). A raw Celery `task_id` is
  an unguessable UUID returned only to the request that enqueued it, but the endpoint should still require
  `require_auth` (no anonymous polling) at minimum. Decide and document whether you also enforce **task
  ownership** (would require persisting a `task_id → user_id/session_id` mapping somewhere — Redis is the
  natural place, cheap TTL) vs. treating the `task_id` itself as an unguessable bearer capability scoped by
  auth-required-but-not-ownership-checked. Either is defensible; pick one, justify it briefly, and make sure
  it doesn't block the guest CV-upload flow (guests get a `task_id` too, per P5-04, even though their result
  isn't persisted to Postgres).
- Keep the router thin (Router → Service, §8) — put the Celery-result-to-API-shape mapping in a small service
  or a pure function that's easily unit-testable without a real Celery worker (inject/construct an
  `AsyncResult`-like object in tests — do not require a live Redis broker for unit tests; a live-broker
  integration test may be added following the P2/P5 convention if you find it valuable).
- Unit tests: pending, in-progress (custom stage), success (with result payload), failure (with safe error
  message), unknown/garbage task_id (Celery defaults unknown ids to `PENDING` — decide if that's the right
  response or if you want to special-case it, and document your choice).

## Acceptance criteria
- [ ] `GET /api/jobs/status/{task_id}` returns a typed status response reflecting the Celery task's actual
      state (pending/in-progress-with-stage/success-with-result/failure-with-safe-message).
- [ ] Endpoint requires authentication (`require_auth`); the ownership-scoping decision (checked vs.
      capability-style) is made explicitly and documented in the report.
- [ ] No internal exception tracebacks/stack traces are ever returned to the client on `FAILURE`.
- [ ] Router stays thin; the Celery-result mapping logic is isolated and unit-testable without a live broker.
- [ ] Works against the exact task-id/state/meta/result shape `P5-04-cv-upload-endpoint`'s Celery task already
      produces (no rework needed on that side) — verify by testing against (or mirroring) its real state
      transitions/meta keys.
- [ ] `ruff`, `mypy`, and the full `pytest` suite pass.

## Design references
- dev-board/plan.md: Phase 5 (implicit — job progress is part of the P5 exit criteria: "async, with
  progress").
- dev-board/app-design-and-features.md: §8 API table (`GET /api/jobs/status/{task_id}`, line 402), §5.3
  Background jobs (Celery) (lines 237-244: "Jobs emit progress (state in Redis) that the UI polls").
- `backend/app/tasks/celery_app.py` (Redis-backed broker + result backend), `backend/app/tasks/profile_ingest.py`
  (the producer: task states/meta/result shape this endpoint must read), `backend/app/api/profile.py` /
  `backend/app/api/chat.py` (thin-router conventions), `backend/app/security/dependencies.py::require_auth`.

## Constraints / non-goals
- No changes to `P5-04-cv-upload-endpoint`'s Celery task internals unless you find its state/meta/result shape
  is genuinely unusable from the outside (call this out explicitly if so, rather than silently reshaping it).
- No frontend work — P5-07 will poll this endpoint from the upload progress UI.
- This endpoint is generic to Celery task ids (not CV-upload-specific) so P6's crawl-progress work can reuse
  it later — do not name things in a CV-only way.
