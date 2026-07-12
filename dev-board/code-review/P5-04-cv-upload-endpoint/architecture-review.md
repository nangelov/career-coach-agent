# Architecture review — P5-04-cv-upload-endpoint · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 target structure | Code lands in `api/`, `services/`, `tasks/`, `schemas/` per module map | Router `app/api/profile.py`, service `app/services/profile_ingest.py`, task `app/tasks/profile_ingest.py`, DTO `app/schemas/profile.py` — each concern in the right module | None |
| A2 | §8 layering (Router→Service→Task/Repository) | Thin router; business logic in service; DB/vector writes via repository helpers, no raw driver in the task | Router owns only HTTP (authN/rate gate, read bytes, map typed rejections→4xx, return 202). Service owns validate+enqueue. Persist goes through `add_kb_chunk`; profile upsert via ORM session — no raw driver | None |
| A3 | interface-before-implementation | Real seams so engines/brokers swap | Service depends on narrow `CvIngestEnqueuer` Protocol (no Celery import in the service). `run_cv_ingestion` injects `DocumentParser`/`CvStructurer`/`EmbeddingClient`/`SessionProvider` — unit-testable with fakes. Clean seams throughout | None |
| A4 | §5.3 Celery, no in-request parse | Enqueue + return 202 `task_id`; parse off the request path (v1 parsed inline, v2 must not) | `POST /api/profile/cv` → 202 `CvUploadResponse{task_id,status}`; parse runs in `ingest_cv` worker task | None |
| A5 | §5.3 progress via Redis | Progress state in Redis; no bespoke second channel | `self.update_state(PARSING→STRUCTURING→PERSISTING)` on Celery's Redis-backed result backend; P5-06-consumable | None |
| A6 | Celery worker composition root | Worker builds its own collaborators (no shared `app.state`); mirror bootstrap lazy posture; register in `celery_app` include | `_ingest_cv_entrypoint` builds parser/router/embedder/PG provider with deferred heavy imports, disposes PG pool + Redis in `finally`; module added to `include=[...]` per `ping.py` convention | None |
| A7 | reuse existing helpers (no re-impl) | Reuse `add_kb_chunk`, `SentenceTransformerEmbeddingClient`, composite parser, `ProfileStructurer`, `detect_format` | All reused; `chunk_text` is a new size-bounded splitter (engineer confirmed no existing splitter util — acceptable, KISS, dependency-free) | None |
| A8 | guest rate-limit reuse (pre-work §6.8) | Guest 1 upload/session via existing `RateLimitService`, not a parallel mechanism | `rate_limiter.enforce(RateLimitAction.UPLOAD, current_user)` before enqueue; `UPLOAD` action already existed | None |
| A9 | §4 data ownership | Right store owns data; user-scoped writes; guests not persisted | Profile JSONB + `KbDocument(user_cv)` + `KbChunk` in Postgres/pgvector keyed on token `user_id` (never request body, §7). Guest (`user_id=None`) parses for preview only, skips persistence (no `users` FK anchor) — documented | None |
| A10 | §5.1 one CV per user | Profile one-row-per-user; exactly one `user_cv` doc | Profile upsert (unique on `user_id`); prior `user_cv` docs bulk-deleted (chunks via ON DELETE CASCADE) before insert → exactly one | None |
| A11 | locked decisions | Postgres+Redis only; in-process sentence-transformers; Celery; LLM failover router; no Mongo/ReAct parser | Structuring via `LLMRouter.from_settings` (failover); embeddings in-process; broker/backend Redis; persistence Postgres/pgvector. All honored | None |
| A12 | phase fit | Defer P5-05 (GET/PUT profile) + P5-06 (jobs status); shape result/state to be consumable | No P5-05/P5-06 endpoints added; result `{profile,persisted,kb_document_id,chunk_count}` + custom states are P5-06-consumable | None |
| A13 | §11 budget posture | free/OSS/self-hosted | docling/tesseract/sentence-transformers OSS; no paid tier introduced | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo)
- [x] Honors locked decisions (no ReAct parser; Postgres+Redis only; SSO-only auth unaffected; in-process embeddings; Celery; failover router)
- [x] Interfaces-before-implementations (`CvIngestEnqueuer` port; `DocumentParser`/`CvStructurer`/`EmbeddingClient`/`SessionProvider` injected)
- [x] Budget posture respected (free/OSS/self-hosted)

## Notes
- **Design-clean seams.** The `CvIngestEnqueuer` port keeps Celery out of the service, and
  `run_cv_ingestion` takes every collaborator by injection — this is the reusable template for
  the remaining §5.3 background jobs (P6 crawl, P9 memory-learn). Blessed; recorded to memory.
- **Guest preview-without-persist** is the architecturally correct resolution of the §4 FK
  reality (no `users` row to anchor a `Profile`/private `KbDocument`) against the pre-work
  "1 upload per guest session" allowance. Consistent with §5.2 ("guests can preview but not
  save"). No change needed.
- **Follow-up (perf, not a gate — cheap to move later):** `_ingest_cv_entrypoint` constructs a
  fresh `SentenceTransformerEmbeddingClient` (loads the embedding model) and a new PG pool on
  **every** task invocation. Correct and KISS for P5, but the model load is heavy per-task; the
  eventual optimization is a worker-process-level singleton (Celery `worker_process_init`) so
  the model/pool are built once per worker. This is a construction-site change over the same
  contract — safe to defer. Recommend logging against a P5-06/perf follow-up.
- **Base64 over the JSON serializer** inflates the broker payload ~33% and routes CV bytes
  through Redis; acceptable given the small, rate-limited uploads and the JSON-serializer
  constraint. Documented by the engineer. No design objection.
- `python-multipart` correctly added to deps + both curated CI lists (kept in sync) — consistent
  with the prior "curated CI light deps" ruling.
- The two pre-existing `tests/test_ingestion_parser.py` curated-venv failures are out of scope
  (owned by the parallel `FIX-04-docling-bytes-import-guard`); not considered here per the
  dispatch note.
