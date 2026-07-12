# Engineer report — P5-06-task-status · Revision 1

## Summary
Added the consumer side of the P5-04 Celery CV-ingest job: a generic
`GET /api/jobs/status/{task_id}` endpoint that reads a Celery task's Redis-backed state via
`AsyncResult` and returns a stable, client-safe status shape. The endpoint is generic to any
Celery task id (no CV-specific naming) so P6's crawl/OCR jobs reuse it. Layering is
Router → Service: the router is thin (auth + offload the blocking lookup), and all
Celery-state→API-shape mapping lives in a pure, broker-free function/service that is unit-tested
without a live Redis/broker.

## Files changed
- `app/schemas/jobs.py` — new. `JobStatusResponse` DTO + `JobStatusValue` literal
  (`pending`/`in_progress`/`success`/`failure`). Generic job-status wire contract, kept
  independent of the ingestion layer (schemas never import agents/tasks).
- `app/services/jobs.py` — new. `map_async_result()` (pure mapping), `JobStatusService`,
  and the narrow `AsyncResultLike`/`AsyncResultFactory` ports (the only Celery seam). Holds the
  client-safe failure/cancelled message constants.
- `app/api/jobs.py` — new. Thin router `GET /api/jobs/status/{task_id}` requiring `require_auth`;
  offloads the blocking `get_status` to a worker thread via `asyncio.to_thread`.
- `app/app_state.py` — added `JOB_STATUS_SERVICE` app-state key.
- `app/bootstrap.py` — added `build_job_status_service()` (lazily wires the factory to
  `AsyncResult(task_id, app=celery_app)`; deferred imports keep API import light).
- `app/main.py` — registered `jobs_router`.
- `tests/test_job_status_service.py` — new. Pure mapping + service unit tests (fake `AsyncResult`,
  no broker), asserting against the exact producer state names / meta keys / result shape.
- `tests/test_jobs_api.py` — new. Router-level tests (override `require_auth` +
  `get_job_status_service`): in-progress/success/failure/pending, guest can poll, missing auth 401.

## Key decisions
- **AuthZ = capability, not ownership** (task's explicit decision point; §7). The endpoint
  requires `require_auth` (no anonymous polling) but does **not** additionally verify the caller
  enqueued the `task_id`. A Celery `task_id` is an unguessable UUID4 handed back only to the
  enqueuing request, so it functions as a bearer capability. Enforcing ownership would require
  persisting a `task_id → user/session` map in Redis (extra state + TTL bookkeeping) and a guest
  branch anyway (guests get a `task_id` but no `user_id`), for negligible gain — YAGNI/KISS. This
  keeps the guest CV-upload flow working: a guest polls their own job with the token they hold.
  Documented in `app/api/jobs.py`'s module docstring.
- **Failure never leaks internals** (acceptance criterion / §9). On Celery `FAILURE` the mapper
  ignores the exception object and returns a single generic `SAFE_FAILURE_MESSAGE`; the real cause
  stays in the worker logs (the producer already logs it). A test asserts a secret-bearing
  exception message does not appear anywhere in the response body. `REVOKED` → generic cancelled
  message.
- **Unknown/garbage task_id → `pending`** (not special-cased). A Redis result backend cannot
  distinguish "never enqueued" from "not started yet" — both are Celery `PENDING`. Special-casing
  would require a separate existence store; documented instead (matches Celery semantics). A test
  covers it.
- **Generic mapping** (design §8 wording is deliberately generic; §5.3). Any *custom* (non-built-in)
  Celery state is treated as `in_progress` and its `meta` dict supplies `stage`/`message` — so the
  service needs no import of the CV task's state names and keeps working for P6 producers. Raw
  Celery `state` is surfaced verbatim (the producer docstring says P5-06 reports the custom states
  verbatim).
- **Blocking-call boundary.** Celery's result-backend API is synchronous; the async router offloads
  `get_status` via `asyncio.to_thread` so a Redis round-trip never blocks the event loop.
- **No changes to the P5-04 producer.** The endpoint reads its exact state/meta/result shape as-is;
  the service test imports `STATE_PARSING/STRUCTURING/PERSISTING` and mirrors the
  `{profile, persisted, kb_document_id, chunk_count}` result to prove no producer rework is needed.

## How to verify
- `cd backend && source .venv/bin/activate`
- `ruff check . && ruff format --check .`
- `mypy app/schemas/jobs.py app/services/jobs.py app/api/jobs.py app/bootstrap.py`
- `python -m pytest tests/test_jobs_api.py tests/test_job_status_service.py -q`
- Full suite: `python -m pytest -q`

## Tests (final step — mandatory)
- `ruff check .` → All checks passed. `ruff format --check .` → 155 files already formatted.
- `mypy` on the changed files → `Success: no issues found in 7 source files`.
- `python -m pytest tests/test_jobs_api.py tests/test_job_status_service.py -q` → **16 passed**.
- Full suite `python -m pytest -q` → **405 passed, 47 skipped** (0 failures).
- **Pre-existing mypy noise (not mine):** a project-wide `mypy app tests` reports 7 errors in 4
  files I did not touch (`tests/test_ingestion_ocr.py`, `tests/test_ingestion_parser.py`,
  `tests/test_llm_router.py`, `tests/test_p4_exit_verification.py`) — `unused-ignore` comments and
  a langgraph node-type mismatch, i.e. local library/mypy version drift. All my changed files pass
  mypy cleanly. Left untouched as out of scope for this task.

## Self-check
- [x] Meets acceptance criteria (typed status reflecting real Celery state; requires auth;
  no traceback leaks; thin router + isolated, broker-free-testable mapping; works against P5-04's
  exact shape; ruff/mypy/pytest green for the change).
- [x] No secrets committed; Router→Service layering respected (router: HTTP only; service: mapping).
- [x] Tests/lints pass (results pasted above).
- [x] AuthZ ownership-scoping decision made explicit and documented (capability model).
