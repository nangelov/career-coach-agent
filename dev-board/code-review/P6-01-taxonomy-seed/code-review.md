# Code review — P6-01-taxonomy-seed · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/app/ingestion/taxonomy_seed.py:246 | Idempotency is delete-then-insert with no unique constraint on `(source_type,source)`; two concurrent seed runs (CLI + Celery) could briefly double-insert before either commits. | Acceptable for an occasional one-time seed. Optionally note the single-runner assumption in the module docstring, or add a partial unique index in a later phase. No change required now. |
| C2 | nit | backend/app/tasks/profile_ingest.py:57 | `chunk_text` is re-exported only implicitly (via the module-level import); `tests/test_profile_ingest_task.py` and P5 exit tests depend on `from app.tasks.profile_ingest import chunk_text` continuing to resolve. Works today but is fragile to an import cleanup. | Optionally add `chunk_text` to an `__all__` or leave a comment that it's a compat re-export. Non-gating. |

## Notes
- **Acceptance criteria all met.** Bundled fixture present (`data/taxonomy_seed.json`, 26 occupations: 16 onet + 10 esco, unique sources, all carry skills) with provenance/licensing in `data/README.md` (ESCO CC BY 4.0, O*NET public domain) and a documented bulk-download upgrade path. Celery `seed_taxonomy_task` + CLI ingest into shared KB (`user_id IS NULL`, `source_type='curated'`) reusing the P2 `EmbeddingClient` + `add_kb_chunk` write path — no second embed/write path, no new `source_type`, no migrations. Idempotent upsert = source-scoped delete then insert in one transaction. Unit tests cover parse/normalize + idempotency with fakes; no live DB/network. No scraping/HTTP anywhere in the path (data read from disk, ML/DB imports deferred).
- **Correctness verified.** Empty-input path never opens a session (tested with an exploding provider). `zip(chunks, embeddings, strict=True)` guards a length mismatch; chunks are always ≥1 since title+description are required non-empty. Delete is correctly scoped to `user_id IS NULL AND source_type='curated' AND source IN (...)` — a user's private CV docs cannot be touched.
- **DRY refactor is clean.** `chunk_text` was moved verbatim (byte-for-byte) from `profile_ingest.py` to `app/ingestion/chunking.py`; no behavior change. Confirmed no other consumer imports the removed `DEFAULT_CHUNK_SIZE/OVERLAP` from `profile_ingest`, and the `chunk_text` name still resolves for the existing test importers.
- **Security:** no untrusted input — static curated fixture, parameterized ORM writes, no network, no arbitrary execution. Nothing to flag.
- **Ran locally:** `pytest tests/test_taxonomy_seed.py tests/test_profile_ingest_task.py -q` → 25 passed; `ruff check` on all P6-01 files → clean. Fixture validity re-confirmed independently.
- **Out of scope / not gated here:** the working tree also contains modified files from the parallel P6-02/P6-03 worktrees (`graph.py`, `web_searcher.py`, `internet_search.py`, `config.py`, `models/market.py`, `models/jobs.py` deletion, `tavily_pool.py`, market migration). Those are not P6-01's changes and are reviewed under their own tasks; the P6-01 file set matches `engineer.md` exactly.
