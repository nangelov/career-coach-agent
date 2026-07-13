# Engineer report — P6-09-manual-verify · Revision 1

## Summary
Verified the **full P6 exit criterion** end-to-end — *"for a target role the app returns cited,
frequency-ranked market requirements and a skills gap; extraction happens once per role, reused
across users; no job listings are ever shown; a job-hunting turn is redirected."* P6-01..P6-08
each proved a piece with fakes on both sides of a seam, but **no single test composed the whole
chain** (mining actually populating the row the requirements API reads back; the cache actually
sparing a second user a re-mine; the graph having no listings path).

Added one cohesive module — `backend/tests/test_p6_exit_verification.py` (10 tests, mirroring
`test_p4_exit_verification.py` / `test_p5_exit_verification.py`) — that drives the **real**
mining pipeline (`mine_role_requirements`), the **real** `RolesService` + `GET /api/roles/...`
router, the **real** compiled multi-agent graph + `ChatService`, the **real** market/learning
repositories and the **real** `SkillsGapService`, faking only the true external edges (extractor
LLM, Tavily pool, crawl transport, embedder). Two authoritative proofs run against live
docker-compose Postgres (migrated to `0007`) and skip cleanly with no DB.

**Conclusion: the current implementation meets the full P6 exit criterion as written.** All 6
task points are covered (table below). One **non-blocking robustness observation** on P6-04's
canonicalization is flagged (see below) — it does *not* break the criterion under the production
condition (P6-01 taxonomy seeded), but is worth a reviewer eye.

Also completed the required **formatting cleanup**: ran `ruff format .` to fix the 6 pre-existing
drift files (`taxonomy_seed.py`, `models/market.py`, `tavily_pool.py`, migration `0007`,
`test_market_models.py`, `test_taxonomy_seed.py`); `ruff format --check .` is now clean.

## Files changed
- `backend/tests/test_p6_exit_verification.py` — **new.** The composed P6 exit verification (10
  tests). Verification-only: **no product code changed**.
- 6 pre-existing P6 files reformatted by `ruff format` (whitespace/style only, no logic change):
  `app/ingestion/taxonomy_seed.py`, `app/repositories/models/market.py`, `app/tools/tavily_pool.py`,
  `migrations/versions/20260713_0007_market_intelligence.py`, `tests/test_market_models.py`,
  `tests/test_taxonomy_seed.py`.

## Key decisions
- **Compose the real chain; fake only external edges** (P4-10/P5-08 precedent). Mining runs the
  real taxonomy→crawl→extract→aggregate→persist over the real provider; the requirements/gap read
  runs the real `RolesService`→`repositories.market`→Postgres; the graph tests run the real
  `GraphTurnStreamer`. Faked: the extraction LLM (scripted forced tool-call), Tavily (`FakeSearchTool`),
  crawl HTTP (`fake_crawl_client` SSRF-guarded MockTransport), embedder (`_FixedEmbedder`, real
  `vector(4096)`).
- **Cache reuse proven through the real endpoint with spies** (point 3): two `GET
  /api/roles/{role}/requirements` calls over the real service; the second asserts `db.sessions == 1`,
  `resolver.calls == 1`, `enqueuer.calls == []` — extraction paid once per role, reused across users.
  A cold-role variant asserts `202` + exactly one *enqueued* mine (never run inline — §7.5).
- **"No listings" proven three ways** (points 4/5): the request-path worker's structured payload has
  only `{chunk_count, role_profiles}` keys (never a posting); the backend OpenAPI surface exposes the
  roles routes and *only* `/api/jobs/status/{task_id}` (no listings/apply/save/track route); a
  frontend source scan finds no `/api/jobs/*` reference beyond the status poller and no
  save/track/apply-to-job call.
- **Live proofs seed the taxonomy first** (the production condition — P6-01 seeds it at deploy) so
  mine and read canonicalize to the same string; this also exercises point 1's taxonomy-hit path
  (baseline skills + taxonomy citation). See the flagged observation for why this matters.
- **Live tests self-clean** (delete role_profiles/job_postings/kb docs by unique source) and skip
  cleanly without a reachable+migrated DB — verified the DB is empty (0 rows) after the full run.

## P6 exit criterion — point-by-point
| # | Criterion | Where proven |
|---|-----------|--------------|
| 1 | mining → **cited, frequency-ranked** requirements at 200 (not a bare skill list) | `test_live_mining_then_requirements_then_gap` (live: real mine persists → real endpoint returns ranked+cited, `evidence_count==3`); `test_worker_only_returns_role_profile_content...` (worker payload is role-profile content only) |
| 2 | skills gap (matched/gap split, ordered) | `test_live_mining_then_requirements_then_gap` (live: Python matched, Kubernetes/SQL gap, descending-frequency order) |
| 3 | **cache reuse — 2nd user, no re-extraction** | `test_second_request_served_from_cache_no_reextraction` (real endpoint×2; DB/resolver hit once, no mine) + `test_cold_role_enqueues_a_single_mine_never_runs_it_inline` (202 + one enqueue) |
| 4 | **redirect, not listings** + off-topic short-circuit | `test_job_hunting_turn_is_redirected_through_the_real_graph` (responder runs, grounded on requirements not listings) + `test_off_topic_turn_short_circuits...` (canned refusal, no worker/responder LLM call) |
| 5 | **no job listings anywhere** (backend + frontend) | `test_no_job_listing_surface_in_backend_api` (OpenAPI: only `/api/jobs/status/{task_id}`) + `test_no_job_listing_surface_in_frontend` (source scan) |
| 6 | learning-resource corpus **queryable** by skill | `test_live_learning_resource_corpus_is_queryable` (live: real JSONB containment, case-insensitive) + `test_learning_resource_lookup_is_wired` (offline seam) |

## Flagged observation (non-blocking) — P6-04 canonicalization over the shared curated corpus
`market_agent._resolve_baseline` / `resolve_canonical_role` canonicalize a role by
hybrid-searching `shared_kb_document_ids(source_types=["curated"])`, which includes taxonomy
occupations **and** role-profile summaries **and** learning resources (all share
`source_type="curated"`, distinguished only by `meta.kind`). It filters by `source_type`, not by
`meta.kind`, so it relies on ranking — not an explicit taxonomy-only filter — to pick the
occupation doc over a role-profile *summary* doc titled `"Market requirements: <role>"`.

- **Impact:** under the production condition (P6-01 taxonomy seeded) the occupation doc reliably
  outranks the summary — I verified this empirically against live Postgres, so the exit criterion
  **holds**. But with *no* matching taxonomy occupation for a role, the read-time canonicalize can
  resolve to the summary's title instead of the mined `role_profiles.canonical_role`, causing
  `get_role_profile` to miss and the endpoint to return a perpetual `202` (re-enqueue) loop.
- **Not patched here** (out of P6-09 scope — verification-only). Suggested follow-up for the
  reviewer/architect to route to **P6-04**: have `_resolve_baseline` restrict the taxonomy match by
  `meta.kind` (e.g. occupation) rather than `source_type` alone. Surfaced, not silently worked around.

## How to verify
```bash
# Backend (from backend/) — mirrors `make check`:
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy app/ migrations/
uv run --no-sync pytest -q                                 # offline (2 live-DB tests skip)
# Full live-DB pass (actually run here, green):
make test-integration        # sources root .env → real Postgres; runs the whole suite
# Frontend (from frontend/):
npm run lint && npm run type-check && npm test -- --watchAll=false
```

## Tests (final step — mandatory)
**Backend** (`backend/`):
- `ruff check .` → **All checks passed!**
- `ruff format --check .` → **203 files already formatted** (6 drift files fixed).
- `mypy app/ migrations/` (CI scope) → **Success: no issues found in 122 source files**;
  `mypy tests/test_p6_exit_verification.py` → **Success** (new file adds no mypy noise).
- `pytest -q` (offline) → **606 passed, 59 skipped** (+8 new offline; 2 new live-DB tests skip
  without Postgres, per convention).
- **Live DB** (`make`-style, root .env → real Postgres @ localhost:5432, migrated to `0007`):
  full suite **664 passed, 1 skipped**; `test_p6_exit_verification.py` **10 passed**. DB confirmed
  empty (0 rows across role_profiles/job_postings/kb_documents/kb_chunks) after the run.

**Frontend** (`frontend/`):
- `npm run lint` → **✔ No ESLint warnings or errors**
- `npm run type-check` → clean (tsc `--noEmit`).
- `npm test` → **16 suites, 151 tests passed**.

No failing tests. No test weakened or deleted; no product code changed.

## Self-check
- [x] Meets acceptance criteria — all 6 P6 points covered by composed/integration tests;
  live-infra parts documented and run green against compose Postgres; `ruff format --check` clean;
  full backend (ruff/format/mypy `app`+`migrations`/pytest) and frontend (lint/type-check/jest)
  suites green; report states the criterion **is met** and precisely flags one non-blocking
  P6-04 observation rather than patching around it.
- [x] No secrets committed; verification-only (no product code changed); Router→Service→Repo/Agent
  layering respected (tests drive the real layered stack, faking only external edges).
- [x] Tests/lints pass (results pasted).
