# Engineer report — P5-04-cv-upload-endpoint · Revision 2

## Summary
Wired the P5-01/02/03 ingestion pipeline end-to-end behind a real, authenticated CV-upload
endpoint that runs the parse as an async Celery job (§5.1 / §5.3). `POST /api/profile/cv`
validates the upload, enforces the guest 1-upload-per-session cap, enqueues a Celery task, and
returns **202** with a `task_id` — no synchronous parsing in the request path (v1 parsed
inline; v2 must not). The Celery task bridges the sync-Celery / async-stack gap and runs
`CompositeDocumentParser → ProfileStructurer → ProfileSchema`, then upserts `profiles.data`
(JSONB) and writes exactly one `KbDocument(source_type="user_cv")` + its embedded `KbChunk`
rows into pgvector, reporting progress via Celery's own Redis-backed state machinery.

## Files changed
- `app/api/profile.py` (new) — thin router: authN/rate-limit gate, read multipart bytes, map
  typed rejections → 400/413/415, return the 202 job handle. No business logic.
- `app/services/profile_ingest.py` (new) — `ProfileIngestService`: validate (empty / size /
  supported format via the shared `detect_format`), base64-encode, enqueue via an injected
  `CvIngestEnqueuer` port (no Celery import in the service). Typed rejection exceptions.
- `app/schemas/profile.py` (new) — `CvUploadResponse` wire DTO (task_id + status). Kept
  independent of the ingestion `ProfileSchema` (endpoint returns only the job handle).
- `app/tasks/profile_ingest.py` (new) — the Celery task `ingest_cv` (`bind=True`,
  `name="tasks.ingest_cv"`), the injectable async core `run_cv_ingestion(...)`, the
  worker-local composition root `_ingest_cv_entrypoint(...)`, `_persist_profile_and_chunks`,
  the `chunk_text` splitter, and the `enqueue_cv_ingest` producer.
- `app/tasks/celery_app.py` — added `app.tasks.profile_ingest` to the `include` list.
- `app/bootstrap.py` — `build_profile_ingest_service` (wires the real enqueuer, lazy import).
- `app/app_state.py` — added `PROFILE_INGEST_SERVICE` app-state key.
- `app/main.py` — register `profile_router`.
- `app/config.py` — added `CV_UPLOAD_MAX_BYTES` (default 10 MiB).
- `pyproject.toml`, `Makefile`, `.github/workflows/backend-ci.yml` — added `python-multipart`
  (FastAPI needs it for file uploads) to deps **and** both curated CI install lists.
- `tests/test_profile_cv_api.py`, `tests/test_profile_ingest_task.py`,
  `tests/test_profile_ingest_persistence.py` (new) — see Tests.

## Key decisions
- **Layering (§8): Router → Service → Task/Repository.** Router owns only HTTP; the service
  owns validate+enqueue behind a narrow `CvIngestEnqueuer` port so it has **no** Celery import
  (unit-testable with a fake); the task owns the pipeline; DB/vector writes go through the
  existing `add_kb_chunk` repository helper, never raw driver calls.
- **Progress = Celery's built-in Redis-backed state machinery** (`self.update_state` with
  `PARSING → STRUCTURING → PERSISTING`), per the task brief — no bespoke second progress
  channel. P5-06's `GET /api/jobs/status/{task_id}` reads exactly this state + meta.
- **Sync→async bridge + standalone-worker composition root.** The task body wraps an async
  impl in `asyncio.run` and constructs its **own** parser / LLM router / embedder / Postgres
  provider inside the worker (Celery workers don't share FastAPI `app.state`), disposing the
  PG pool + Redis client in a `finally`. All heavy imports (docling/sentence-transformers/
  redis/router) are deferred **inside** the builder so importing the module (needed by the API
  composition root for `enqueue_cv_ingest`) stays light — no ML stack at import (curated-CI
  safe).
- **Guest handling (design §4 + FK reality).** A guest (`user_id=None`) has no `users` row to
  anchor a `Profile`/private `KbDocument` (FK-required) and gets no persisted history (§4). So
  the task still parses + structures (progress + result observable for preview, matching
  "guests can preview but not save") but **skips Postgres persistence**. Documented in the
  task and service. Guest upload is still capped at 1/session via the existing
  `RateLimitService` (`RateLimitAction.UPLOAD`).
- **Re-upload keeps exactly one CV doc.** Persist upserts the profile in place and bulk-deletes
  any prior `user_cv` `KbDocument` (child chunks removed by the ON DELETE CASCADE FK) before
  inserting the fresh one — so re-uploading leaves exactly one document (asserted in the
  live-DB test).
- **Result shape is P5-06-consumable** (`{profile, persisted, kb_document_id, chunk_count}`)
  without rework, per the non-goal coordination note.
- **Base64 over the JSON serializer.** Celery is configured with the JSON serializer (can't
  carry raw `bytes`); CVs are small and uploads are rate-limited, so base64 is cheap.
- **`python-multipart` was missing entirely** from deps and both curated lists — FastAPI
  requires it for `UploadFile`. Added to all three (kept Makefile + CI lists in sync).
- Errors are **not swallowed**: `DocumentParseError` / `ProfileStructuringError` propagate out
  of the task → Celery `FAILURE` with the message.

## How to verify
- `make lint format-check typecheck` (mypy scope is `app/ migrations/`, per CI).
- `uv run --no-sync pytest` — full suite.
- Manual: `POST /api/profile/cv` (multipart `file`, bearer token) → `202 {task_id,...}`; poll
  the Celery result/state (P5-06) for `PARSING/STRUCTURING/PERSISTING` → `SUCCESS`.

## Tests (final step — mandatory)
- **Canonical dev `.venv` (`uv run --no-sync pytest`): 376 passed, 45 skipped.** Green.
- **CI-equivalent curated venv** (rebuilt fresh because I changed the curated dep list —
  added `python-multipart`): `ruff check` ✅, `ruff format --check` ✅, `mypy app/ migrations/`
  ✅ (no issues, 89 files), and my three new test files **14 passed, 1 skipped** (the live-DB
  persistence test skips with no Postgres).
- **Two pre-existing failures in the curated venv are NOT mine and NOT in scope:**
  `tests/test_ingestion_parser.py::test_parse_bytes_source_*` fail there with
  `ModuleNotFoundError: docling_core` — they are P5-01/02 parser tests (the file is **untracked
  / not in HEAD**, part of the uncommitted P5 ingestion work), they don't `importorskip`
  docling on the bytes path, and they **pass** in the full `.venv` where docling is installed.
  I did not modify another task's tests. CI only type-checks `app/ migrations/` (not `tests/`),
  so the unused-`type: ignore` differences in those untracked test files never gate the
  pipeline either. My P5-04 code and tests are green in both environments.

## Self-check
- [x] Meets acceptance criteria (202 + task_id, no in-request parse; full pipeline runs on a
  fixture in a hermetic test; profile upsert + one `user_cv` doc + embedded chunks; progress
  via Celery state; guest 1-upload cap via existing `RateLimitService`; errors → FAILURE;
  ruff/mypy/pytest pass).
- [x] No secrets committed; Router→Service→Task/Repository layering respected.
- [x] Tests/lints pass (results pasted above).

---

# Revision 2 — response to code review

## Summary of changes
Addressed the two gating findings (C1 major, C2 minor) plus the cheap nit C3; C4 deferred with
rationale (matches the architect's own follow-up note). The upload path now enforces the size
cap **before** materializing the body and validates **before** charging the rate-limit budget.

## Files changed (this pass)
- `app/api/profile.py` — new `_read_within_cap(file, max_bytes)` helper: a pre-read guard on
  `file.size` (Starlette-populated) rejects an oversized upload with 413 before a single byte
  is read, backed by a bounded chunked read (`_READ_CHUNK_BYTES`) that caps total bytes in
  memory even when `size` is absent/understated. Reordered `upload_cv`: **capped-read →
  validate → charge rate limit → enqueue** (was: charge → full `file.read()` → validate).
- `app/services/profile_ingest.py` — exposed `max_upload_bytes` property (router reads the cap
  without reaching into a private field); renamed `_validate` → public `validate` so the router
  can validate before charging the budget; `submit` still re-runs `validate` (idempotent,
  defense in depth).
- `app/tasks/profile_ingest.py` — `_ingest_cv_entrypoint` now constructs collaborators **inside**
  the `try` with `redis_client`/`db` initialized to `None` and guarded `finally` cleanup, so a
  constructor failure part-way through no longer leaks an already-opened Redis client (C3).
- `tests/test_profile_cv_api.py` — added: `test_read_within_cap_rejects_on_size_before_reading`
  (pre-read guard, with a fake upload whose `.read()` asserts-if-called), `..._rejects_on_overflow_when_size_unknown`
  (bounded read when `size=None`), `..._returns_body_within_cap`, and
  `test_rejected_upload_does_not_consume_guest_budget` (C2: a 415 leaves the guest's single
  upload intact so a following valid CV still 202s).

## Response to review
| id | severity | resolution |
|----|----------|-----------|
| C1 | major | **Fixed.** Size cap is now enforced *before* the body is materialized. `_read_within_cap` first short-circuits on `file.size > max_bytes` (no read at all), then reads in 1 MiB chunks and rejects on overflow so an absent/understated `size` still can't exceed the cap in RAM — the service's post-read length check is now defense-in-depth, not the sole guard. Pre-read rejection is covered by `test_read_within_cap_rejects_on_size_before_reading` (fake `.read()` raises `AssertionError` if reached), plus a bounded-read overflow test. |
| C2 | minor | **Fixed.** Reordered to validate (size/type/empty) **before** `rate_limiter.enforce(UPLOAD, ...)`. A rejected upload no longer consumes the guest's single per-session upload; `test_rejected_upload_does_not_consume_guest_budget` asserts a 415 is followed by a successful 202. Abuse-prevention intent preserved — the body is still read under the cap (C1) before validation, so no unbounded read precedes rate-limiting. |
| C3 | nit | **Fixed.** Collaborators are built inside the `try`; `redis_client`/`db` start as `None` and the `finally` closes whatever was opened, so a failure in `SentenceTransformerEmbeddingClient()`/`PostgresConnectionProvider.from_settings()` no longer leaks the Redis client. |
| C4 | nit | **Deferred (noted).** Deferring embedder/PG construction past the guest early-return would move that decision out of the injected `run_cv_ingestion` seam (the collaborators are injected, and the guest branch lives inside it). The architecture review independently flagged per-task construction of the embedder/PG pool as a `worker_process_init` singleton follow-up over the same contract — C4 folds into that perf change rather than complicating the composition root now (KISS/YAGNI). Not gating. |

## Verification (revision 2)
- `make lint format-check typecheck` — ruff check ✅, ruff format --check ✅ (146 files), mypy
  ✅ (no issues, 89 files).
- `uv run --no-sync pytest` — **380 passed, 45 skipped** (was 376; +4 new tests). Green.
- Curated-CI posture **unchanged this pass**: no dependency changes; all new/changed imports
  are light (`fastapi`, the service, `pytest`) — no ML stack pulled at import, so the curated
  venv install lists are untouched and the new API tests run without docling/sentence-transformers.
