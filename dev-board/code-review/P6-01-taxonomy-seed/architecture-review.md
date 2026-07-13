# Architecture review — P6-01-taxonomy-seed · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Ingestion logic under `ingestion/`, Celery under `tasks/`, data fixture bundled | `ingestion/taxonomy_seed.py` (core) + `ingestion/data/` (fixture+README) + `tasks/taxonomy.py` (thin wrapper) + `ingestion/chunking.py` | Correct placement. None |
| A2 | Layering (Router→Service→Agent/Repo) | Datastore writes via repository helpers, not a hand-rolled path | Chunk writes go through `repositories.vector_search.add_kb_chunk`; task builds worker-local embedder+PG provider and disposes pool | Minor SoC note (see Notes N1) — not a blocker |
| A3 | Shared-KB ownership (§4, §5.6, §6 dec.15) | Occupations written as shared `kb_documents` (`user_id IS NULL`, existing `source_type='curated'`), skills in `meta` | `user_id=None`, `source_type="curated"` (no new check-constraint value), `source="<taxonomy>:<id>"`, skills in `meta` JSONB + folded into embeddable text | Matches. None |
| A4 | Reuse-not-reinvent (task refs, P2) | Reuse P2 `EmbeddingClient` + `add_kb_chunk`, no second embed/write path | `run_taxonomy_seed` injects `EmbeddingClient`, embeds once, writes via `add_kb_chunk`; `chunk_text` extracted to shared `ingestion/chunking.py` (profile_ingest now imports it — DRY) | Matches. None |
| A5 | Idempotency (acceptance) | Re-run must not duplicate rows, keyed on taxonomy id/source | Delete-by-source (shared+curated) then insert, one transaction; chunks cascade via FK; in-fixture duplicate `source` rejected at parse | Correct. None |
| A6 | No scraping / no live HTTP (locked, §5.6, §6 dec.15) | Bundled static fixture only, no runtime external calls | Checked-in JSON read from disk; ML/DB imports deferred; README documents provenance (ESCO CC BY 4.0, O*NET public domain) + upgrade path | Matches. None |
| A7 | Product scope (§1.1/§5.6/§6 dec.11) | Populate shared taxonomy corpus, not a job-board surface | Seeds `kb_documents` only; no browsable listing surface introduced | Conforms to locked coaching scope. None |
| A8 | Phase boundary (task non-goal) | Do NOT touch `role_profiles`/`job_postings`, no migrations here | No migration in this task's diff; the `0007_market_intelligence` migration in the tree is P6-02's (its own docstring) landing in parallel | Correctly scoped. None |
| A9 | Celery orchestration (locked stack) | Async seed as a Celery task registered on the worker | `seed_taxonomy_task` (`bind=True`, Redis-backed `update_state` progress) + module added to `celery_app` `include`; in-process CLI for one-off runs | Matches. None |
| A10 | Budget posture (§11) | Free/OSS/self-hosted, in-process embeddings | In-process `SentenceTransformerEmbeddingClient`; no paid API in path | Matches. None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — see N1 (minor)
- [x] Honors locked decisions (no ReAct parser; Postgres+Redis only; in-process embeddings; Celery async)
- [x] Interfaces-before-implementations — injectable `EmbeddingClient` + structural `SessionProvider` Protocol seam let unit tests drive the core with fakes (no live DB/network)
- [x] Budget posture respected (free/OSS/self-hosted)

## Notes
- **N1 (minor, cheap-to-fix-later — logged follow-up, not a gate).** `ingestion/taxonomy_seed._upsert_occupations`
  imports the `KbDocument` ORM model directly and issues its own `delete(KbDocument)...` + `session.add(document)`
  inline. Chunk writes correctly go through the `vector_search` repository helper, but the document delete/insert
  bypasses the repository layer, so a small amount of datastore access leaks into the ingestion module. This
  mirrors the established P5 ingestion pattern and the caller-owns-transaction contract, so it is consistent and
  acceptable now; if a third writer of shared curated docs appears, promote a
  `repositories.vector_search.replace_curated_document(s)` helper and route both through it. Recorded for P6-04
  (mined-postings ingestion) consistency.
- No design decisions re-litigated; `source_type` vocabulary, embedding dim (4096), and shared-corpus ownership
  (§4 line 185: "populated by the market-intelligence ingestion pipeline; no other phase writes it") all honored.
