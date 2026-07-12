---
name: pattern-celery-ingest-composition-root
description: Blessed P5 Celery background-job template — injected core + worker-local composition root + guest preview-no-persist; reuse for P6 crawl / P9 memory-learn
metadata:
  type: project
---

The P5-04 CV-ingest task set the template for §5.3 Celery background jobs. Reuse it for the
remaining async jobs (P6 web-crawl, P9 memory-learn) rather than re-litigating structure.

**Shape (all four seams present):**
- **Service holds a narrow enqueue Protocol port** (`CvIngestEnqueuer`) so the service has NO
  Celery import; the composition root wires the real producer function (`enqueue_*`).
- **Injected async core** (`run_*_ingestion(*, parser, structurer, embedder, db, progress)`) —
  every collaborator passed in, so unit tests drive it with fakes (no docling/HF/Postgres).
- **Worker-local composition root** (`_*_entrypoint`) builds parser/LLMRouter/embedder/PG
  provider **inside the worker** (Celery does not share FastAPI `app.state`), with heavy imports
  deferred so importing the module for the producer stays ML-free; disposes PG pool + Redis in
  `finally`. Sync task body bridges via `asyncio.run`.
- **Progress = Celery `self.update_state` (Redis-backed)** — no bespoke progress channel; the
  status endpoint (P5-06) reads that state/meta verbatim.

**Why:** clean swap seams (§8 interface-before-implementation), request path never blocks on
slow work (§5.3), and errors propagate → Celery `FAILURE` (not swallowed).

**Guest handling ruling:** a guest (`user_id=None`) has no `users` row to anchor an FK-required
`Profile`/private `KbDocument`, so the task **parses + structures for preview but skips Postgres
persistence** — consistent with §5.2 ("guests preview, not save") and the pre-work "1 upload per
guest session" allowance. This is the correct resolution of the §4 FK reality; do not require
guest persistence.

**How to apply:** when reviewing a new Celery job, expect these four seams + the guest-skip rule.
Accepted follow-up (not a gate): per-task construction of a heavy embedder/model is fine for now
but the eventual optimization is a worker-process-level singleton (`worker_process_init`).

Related: [[ruling-curated-ci-light-deps]] (new light deps like python-multipart go in both
curated CI lists + Makefile), [[pattern-worker-node-di-scope]].
