# Engineer report — P6-01-taxonomy-seed · Revision 1

## Summary
Built the taxonomy-seed ingestion pipeline: a bundled, static ESCO/O*NET occupation+skill
subset is loaded from disk (no scraping / no live HTTP) and idempotently ingested into the
**shared** KB (`kb_documents.user_id IS NULL`, `source_type='curated'`) with embedded
`kb_chunks`, reusing the P2 `EmbeddingClient` + `vector_search.add_kb_chunk` write path.
Exposed as a Celery task plus a thin in-process CLI. Re-running replaces docs per `source`
(keyed on `"<taxonomy>:<id>"`) — no duplicate rows.

## Files changed
- `backend/app/ingestion/data/taxonomy_seed.json` — new: 26 curated occupations (ESCO + O*NET),
  each with title/description/skills. Representative tech/data/AI/PM subset.
- `backend/app/ingestion/data/README.md` — new: provenance/licensing (ESCO CC BY 4.0, O*NET US
  public domain — both free to redistribute) + the documented upgrade path to the full bulk download.
- `backend/app/ingestion/taxonomy_seed.py` — new: the injectable core. `TaxonomyOccupation`,
  `parse_occupations`/`load_seed_occupations` (parse+validate+normalize), and `run_taxonomy_seed`
  (embed → idempotent upsert via delete-by-source-then-insert in one transaction).
- `backend/app/ingestion/chunking.py` — new: extracted the shared `chunk_text` splitter here
  (ingestion concern, reused by both CV ingest and taxonomy seed — DRY).
- `backend/app/tasks/taxonomy.py` — new: `seed_taxonomy_task` (Celery, Redis-backed progress) +
  `main()` CLI (`python -m app.tasks.taxonomy [--path]`), worker-local composition root.
- `backend/app/tasks/profile_ingest.py` — now imports `chunk_text` from `app.ingestion.chunking`
  (removed the local copy + its constants); behavior unchanged, re-exported so existing imports hold.
- `backend/app/tasks/celery_app.py` — added `app.tasks.taxonomy` to the worker `include` list.
- `backend/tests/test_taxonomy_seed.py` — new: parse/normalize + idempotent-upsert unit tests (fakes only).

## Key decisions
- **Reused existing vocabulary/helpers, no new schema.** `source_type="curated"` (existing
  `ck_kb_documents_source_type` value — not a new one), `source="<taxonomy>:<id>"`, skills in
  `meta` JSONB; writes via `add_kb_chunk` (no second embed/write path). No migrations (P6-02 owns
  `role_profiles`/`job_postings`). Refs: task scope, §5.6, §6 decision 15.
- **Idempotency = delete-by-source then insert, one transaction.** Bulk-delete shared curated docs
  whose `source` is in the batch (chunks cascade via FK), then insert fresh — mirrors the P5 CV
  "replace" pattern, guarantees exactly one doc per source on any re-run.
- **Extracted `chunk_text` to `app/ingestion/chunking.py`** rather than importing it from a task
  module (avoids an ingestion→tasks dependency and duplication). Chunking is an ingestion concern (SoC/DRY).
- **Testable core split from Celery/CLI wiring** (same shape as `profile_ingest`): logic in
  `ingestion/`, thin `tasks/` wrapper builds worker-local embedder + Postgres provider and disposes the pool.
- **No network anywhere:** data is a checked-in JSON read from disk; ML/DB imports deferred so the
  module imports light for the Celery `include`.

## How to verify
- Unit: `cd backend && .venv/bin/python -m pytest tests/test_taxonomy_seed.py -q`
- Refactor intact: `.venv/bin/python -m pytest tests/test_profile_ingest_task.py -q`
- CLI: `python -m app.tasks.taxonomy --help` (real run: `python -m app.tasks.taxonomy` against a live DB).
- Fixture sanity: 26 occupations, both `esco` + `onet` taxonomies, unique sources.

## Tests (final step — mandatory)
- `pytest tests/test_taxonomy_seed.py tests/test_profile_ingest_task.py -q` → **25 passed**.
- Full suite: `.venv/bin/python -m pytest -q` → **521 passed, 57 skipped** (skips are live-DB/ML
  tests, unchanged). No failures.
- `ruff check` (all new/changed files) → **All checks passed**.
- `mypy` (new modules + refactored `profile_ingest`) → **Success: no issues found**.

## Self-check
- [x] Meets acceptance criteria (bundled fixture w/ provenance; Celery task ingests to shared KB +
      embeds chunks; idempotent upsert; unit tests for parse + idempotency w/ fake repo; no scraping/HTTP).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (core in ingestion, DB
      access only via repository helpers/session, task is thin wiring).
- [x] Tests/lints pass (pasted above).
