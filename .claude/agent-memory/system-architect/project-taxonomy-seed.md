---
name: project-taxonomy-seed
description: Blessed P6-01 shared-KB taxonomy-seed pattern + the ingestion→repository write-layering ruling for P6-04
metadata:
  type: project
---

P6-01 (taxonomy seed) APPROVED rev 1. The pattern that populates the shared RAG corpus
(§4 line 185: "shared corpus populated by the market-intelligence ingestion pipeline; no
other phase writes it").

**Blessed shape (reuse for P6-04 mined-postings ingestion):**
- Testable core in `ingestion/taxonomy_seed.py` (injectable `EmbeddingClient` + structural
  `SessionProvider` Protocol → unit tests use fakes, no live DB/network); thin Celery+CLI
  wrapper in `tasks/taxonomy.py` (worker-local composition root, deferred ML/DB imports,
  disposes pool). Same split as `profile_ingest`.
- Shared KB write = `kb_documents` `user_id=None`, `source_type="curated"` (existing
  `ck_kb_documents_source_type` value — do NOT add new ones), `source="<taxonomy>:<id>"`,
  skills in `meta` JSONB + folded into embeddable text. Chunk writes via
  `repositories.vector_search.add_kb_chunk` (no second embed/write path).
- Idempotency = delete-by-source (shared+curated) then insert, one transaction; chunks
  cascade via FK. In-fixture duplicate source rejected at parse.
- No scraping / no live HTTP: checked-in JSON fixture read from disk (`ingestion/data/`),
  README documents provenance (ESCO CC BY 4.0, O*NET US public domain) + upgrade path.
- `chunk_text` lives in shared `ingestion/chunking.py` (DRY — both CV ingest and taxonomy
  seed import it; do not re-import from a task module).

**Why:** §5.6/§6 dec.11+15 — taxonomy-first market intelligence, coaching scope (NOT a job
board). Free/OSS/self-hosted, in-process embeddings.

**How to apply:** P6-01 does NOT own migrations — `role_profiles`/`job_postings` (the
`0007_market_intelligence` migration) belong to P6-02, landing in parallel. Do not fault a
P6 task for the other's migration in the tree; check the migration docstring's own task id.

**Logged minor (non-gate) follow-up:** `_upsert_occupations` imports `KbDocument` and issues
`delete`/`session.add` inline — a small datastore-access leak into the ingestion module
(chunks go through the repo helper; docs don't). Accepted because it mirrors P5 and honors
caller-owns-transaction. If a 3rd writer of shared curated docs appears (P6-04), promote a
`vector_search.replace_curated_document(s)` repo helper and route both through it.
