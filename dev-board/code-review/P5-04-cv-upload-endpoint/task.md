# Task P5-04-cv-upload-endpoint — POST /api/profile/cv Celery task + progress + pgvector embed
- **Phase:** P5   **Status:** ENG   **Tags:** (B)

## Scope
tasks.md item: "`POST /api/profile/cv` runs parsing as a **Celery task** (progress via Redis) → store
profile (JSONB) + embed chunks into pgvector."

This wires the P5-01/02/03 ingestion pipeline (`CompositeDocumentParser` → `ProfileStructurer` →
`ProfileSchema`) end-to-end behind a real upload endpoint, running as an async **Celery** job (design §5.3:
"Jobs emit progress (state in Redis) ... UI polls or receives via SSE"). Add:

1. **`POST /api/profile/cv`** (multipart upload, authenticated — `require_auth`, following the pattern in
   `app/api/chat.py` / `app/security/dependencies.py`): accepts a CV file (PDF/DOCX/PPTX/image), validates
   size/type, enqueues a Celery task, and returns **immediately** with a `task_id` (HTTP 202) — no blocking
   parse in-request (design §5.3 / v1 parity note: v1 did this synchronously, v2 must not).
2. **A Celery task** in `app/tasks/` (new module, e.g. `profile_ingest.py`; register it in
   `celery_app.py`'s `include` list per the existing `ping.py` convention) that:
   - Runs `CompositeDocumentParser().parse(...)` → `ProfileStructurer.structure(...)` → `ProfileSchema`.
   - Reports progress via Celery's own state machinery (`self.update_state(state=..., meta=...)`), which is
     already Redis-backed (`celery_app` `backend=settings.REDIS_URL`) — this **is** "progress via Redis";
     do not invent a second bespoke progress channel unless you have a concrete reason the built-in one
     doesn't fit (state it in your report if so).
   - Persists the result: upsert the user's `profiles.data` JSONB row (see
     `app/repositories/models/identity.py::Profile` — one row per user, `unique=True` on `user_id`) with the
     structured profile, **and** writes a `KbDocument` (`source_type="user_cv"`, `user_id=...`) + its chunked,
     embedded `KbChunk` rows into pgvector via the existing `app/repositories/vector_search.py`
     (`add_kb_chunk`) + `app/llm/embeddings.py` (`SentenceTransformerEmbeddingClient`) — reuse these, do not
     re-implement chunking/embedding from scratch. Chunk the parsed document's markdown/text (a simple
     size-bounded splitter is fine; note any existing splitter utility in the codebase first).
   - **Celery tasks are sync and this codebase's DB/embedding stack is async-only** (`PostgresConnectionProvider`
     is `AsyncEngine`-based, `SentenceTransformerEmbeddingClient.embed_documents` is a coroutine). The task
     body must bridge this (e.g. `asyncio.run(...)` around an async implementation function), constructing
     its own `PostgresConnectionProvider.from_settings()` / embedder / parser instances **inside the worker
     process** (Celery workers don't share `app.state` with FastAPI) — mirror the lazy-construction posture
     `bootstrap.py` uses for the API process, adapted for a standalone worker. Document this decision clearly.
   - On failure, leaves the task in Celery's `FAILURE` state with a useful error message (caught via the
     single `ProfileStructuringError` / `DocumentParseError` types from P5-01/02/03) — do not swallow errors.
3. Reuse the profile upload/rate-limit posture already locked for guests: **guests get 1 document upload per
   guest session** (tasks.md pre-work decision, already Redis-enforced per P3-04's rate-limiting service —
   check `app/services/rate_limiting.py` for the existing `RateLimitAction`/`RateLimitService` and add/reuse
   an action for CV upload; do not build a parallel rate-limit mechanism).

Do **not** implement `GET/PUT /api/profile` (P5-05) or `GET /api/jobs/status/{task_id}` (P5-06) in this
task — but do design the Celery task's return/state shape so those endpoints can consume it directly without
rework (coordinate via the acceptance criteria below).

## Acceptance criteria
- [ ] `POST /api/profile/cv` accepts a multipart file upload from an authenticated (or guest) session,
      validates it, enqueues the Celery task, and returns `202` with a `task_id` — no synchronous parsing in
      the request path.
- [ ] The Celery task runs the full P5-01→P5-03 pipeline end-to-end on a real fixture file in a test (using
      Celery's eager/`task_always_eager` test mode or a direct function-level test of the async task body —
      follow whatever pattern keeps tests fast and hermetic; no real Postgres/Redis/HF required for the unit
      tests, but note any live-DB-gated integration test added, matching the P2 `importorskip`/live-DB test
      convention).
- [ ] On success: `profiles.data` is upserted (create if absent, else update) with the structured profile;
      exactly one `KbDocument(source_type="user_cv")` + its `KbChunk` rows (with real embeddings via the
      injected/testable embedder) are written for the user.
- [ ] Progress/state is observable via Celery's built-in state machinery (Redis-backed) during the parse.
- [ ] Guest CV-upload rate limit (1 per guest session) is enforced via the existing `RateLimitService` — not
      a new mechanism.
- [ ] Errors surface as a Celery `FAILURE` state with a clear message, not a silent no-op or an unhandled
      exception with no state update.
- [ ] `ruff`, `mypy`, and the full `pytest` suite pass (`docling`/live-DB-dependent tests may skip gracefully
      as established in P5-01/P5-02).

## Design references
- dev-board/plan.md: Phase 5 (line 99)
- dev-board/app-design-and-features.md: §5.1 (pipeline end state: "embed chunks → pgvector; profile JSONB →
  Postgres", line 208), §5.3 Background jobs (Celery) (lines 237-244: "Jobs emit progress (state in Redis)
  that the UI polls or receives via SSE"), §8 API table (`POST /api/profile/cv`, line 397), guest rate-limit
  pre-work decision (10 messages + **1 document upload** per guest session).
- `backend/app/repositories/models/identity.py::Profile`, `backend/app/repositories/models/knowledge.py`
  (`KbDocument`/`KbChunk`), `backend/app/repositories/vector_search.py::add_kb_chunk`,
  `backend/app/llm/embeddings.py`, `backend/app/tasks/celery_app.py` + `ping.py` (task registration
  convention), `backend/app/api/chat.py` (thin-router / dependency-injection convention),
  `backend/app/services/rate_limiting.py` (existing rate-limit service to extend, not duplicate).

## Constraints / non-goals
- No `GET/PUT /api/profile` — P5-05 (but keep the stored shape consumable by it).
- No `GET /api/jobs/status/{task_id}` — P5-06 (but keep Celery task-id/state consumable by it — this is the
  producer side of that consumer).
- No frontend work — P5-07.
- No VLM-OCR — still just the reserved seam from P5-02.
- Router → Service → Agent/Repository layering: the FastAPI router stays thin; business logic (enqueue,
  validation) belongs in a service; DB/vector writes go through the existing repository helpers, not raw
  driver calls from the task.
