# Task P6-01-taxonomy-seed — ESCO/O*NET taxonomy seed into the shared KB
- **Phase:** P6   **Status:** ENG   **Tags:** (B)
## Scope
tasks.md P6 bullet 1: "Taxonomy seed (no scraping) — ingest ESCO / O*NET occupations + skills into the
**shared** KB (`kb_documents.user_id IS NULL`)." This finally populates the RAG corpus that no earlier phase
owned.

Build an `ingestion/taxonomy_seed.py` (or a small `ingestion/taxonomy/` package) that loads a **bundled, static
seed dataset** (no live scraping/API calls at runtime — check in a curated JSON/CSV fixture of a representative
subset of ESCO and/or O*NET occupations + their associated skills, e.g. 20-50 occupations relevant to tech/AI/PM
career paths, enough for later phases and tests to exercise real data) and writes each occupation as a
`kb_documents` row (`user_id = NULL`, `source_type = "curated"` — the existing check-constraint vocabulary in
`repositories/models/knowledge.py`, do not add a new `source_type` value — `source = "esco:<id>"` or
`"onet:<id>"`, title = occupation name, `meta` JSONB with the occupation's skill list + taxonomy id) with
chunked, embedded `kb_chunks` rows (reuse the P2 `EmbeddingClient` + `repositories/vector_search.py`
`add_kb_chunk` write helper — do not hand-roll a second embedding/write path).

Expose this as an idempotent **Celery task** (`tasks/taxonomy.py`, e.g. `seed_taxonomy_task`) plus a thin CLI/
management entry point so it can be (re)run on demand — it is a one-time/occasional seed, not a per-request path.
Re-running must be safe (upsert/dedupe by taxonomy id + source, not duplicate rows on every run).

Document, in the module docstring, the path to swap the bundled fixture for a real ESCO/O*NET bulk-download
later (this task's job is the ingestion *pipeline*, not sourcing the full live dataset).

## Acceptance criteria
- [ ] A bundled seed fixture (JSON/CSV) of occupations + skills is checked into the repo (`backend/app/ingestion/
      data/` or similar), sourced from/representative of ESCO or O*NET vocabulary, with an explicit note on
      provenance/licensing (both ESCO (EU, free) and O*NET (US, public domain) are free to redistribute — confirm
      and cite the source in a comment/README).
- [ ] `seed_taxonomy_task` (Celery) ingests the fixture into `kb_documents` (`user_id IS NULL`) + embeds chunks
      into `kb_chunks` via the existing embedding/pgvector helpers from P2.
- [ ] Re-running the task does not create duplicate rows (idempotent upsert keyed on taxonomy id/source).
- [ ] Unit tests cover the parse/normalize step and the idempotent-upsert behavior with a fake repository (no
      live DB/network required for the unit suite).
- [ ] No scraping and no live external HTTP calls happen anywhere in this task's code path.

## Design references
- dev-board/plan.md: Phase 6, bullet 1  ·  dev-board/app-design-and-features.md §5.6 ("Why taxonomy-first"),
  §6 decision 15
- Reuse: `backend/app/llm/embeddings.py` (EmbeddingClient), `backend/app/repositories/vector_search.py`,
  `backend/app/repositories/postgres.py` kb_documents/kb_chunks models (P2), `backend/app/tasks/` Celery app (P0)

## Constraints / non-goals
- No live ESCO/O*NET API integration or web scraping in this task — a bundled static fixture is sufficient and
  intentional (documented upgrade path only).
- Do not touch `role_profiles` / `job_postings` (that's P6-02, landing in parallel — do not add migrations here).
