# Engineer report — P6-06-learning-resource-corpus · Revision 1

## Summary
Added the §5.7 **learning-resource corpus** as a sibling pipeline to P6-04's market-intel miner:
discover (Tavily) → crawl provider course pages (SSRF-guarded, robots-respecting, rate-limited)
→ fence untrusted page + **forced-tool-call** normalization → embed + idempotently upsert into the
**shared** KB (`kb_documents`/`kb_chunks`, `user_id IS NULL`, `source_type="curated"`),
**skill-keyed** in `meta` and TTL-stamped, so P7's PDP can join `skill → resources`. Crawling is
**Celery-only**, never a request path. No new migration (reuses the P2 schema).

## Files changed
- `app/ingestion/learning_resources.py` (new) — the injectable, testable pipeline core
  (`discover_learning_resources`) + forced extraction tool schema + normalization/dedup/persist.
- `app/tasks/learning_resources.py` (new) — thin Celery wrapper (`tasks.mine_learning_resources`)
  + CLI; worker-local composition (mirrors `tasks/market.py`).
- `app/ingestion/crawl.py` (new) — **shared** SSRF-guarded page/`robots.txt` fetch helpers,
  extracted so this pipeline reuses the (subtle) line-preserving robots fetch instead of a second
  copy (DRY). See note below re: market_agent.
- `app/repositories/learning_resources.py` (new) — `list_resources_for_skill` (JSONB `@>`
  containment on lowercased `skill_keys`) — the P7 read; layering kept off the driver (§8).
- `app/tasks/celery_app.py` — added the task module to the `include` list.
- Tests (new): `tests/test_learning_resources.py`, `tests/test_crawl.py`.

## Key decisions
- **Core in `app/ingestion/` (not `agents/`)** — there is no request-path worker for this corpus
  (only mining + P7's later read), so it follows the `taxonomy_seed.py` precedent (testable core +
  Celery wrapper), with market_agent's forced-tool-call extraction pattern layered in (§5.7/§6).
- **Extracted shared crawl transport (`app/ingestion/crawl.py`)** rather than re-deriving the
  page/robots fetch. The robots fetch must preserve line structure (whitespace-collapsing silently
  drops every `Disallow` — the C1 defect market_agent already fixed); centralizing it avoids
  repeating that bug. Per the task's "do not modify market_agent" constraint, market_agent keeps
  its equivalent private copies; consolidating it onto this module is a documented follow-up.
- **Provider allowlist** (`PROVIDER_HOSTS`: Coursera/Udacity/Udemy/edX/Pluralsight/FutureLearn) —
  only recognized course-provider hosts are crawled (§5.7 "prefer official providers over marketing
  pages", §10 ToS). LinkedIn Learning is deliberately excluded (ToS). Everything else Tavily
  surfaces is dropped, which also bounds cost.
- **Skill-keyed `meta`** — stores the normalized shape (`title/provider/level/duration/cost/url/
  skills`) plus a lowercased `skill_keys` list and a `refreshed_at` TTL marker; the P7 read is a
  single case-insensitive JSONB containment — no new index/migration.
- **Dedup + idempotency on the normalized URL** — URL is normalized (drop fragment/query, lower
  host, strip trailing slash); a URL surfaced across several skills collapses to one document whose
  covered-skills is the union; persist deletes any prior curated doc for the `source` key before
  inserting (chunks cascade), so a re-mine updates rather than duplicates.
- **Reused, not duplicated:** `RobotsChecker`/`HostRateLimiter` (source_policy), `build_guarded_
  client`/`read_capped` (ssrf_guard), `fence_untrusted` (guardrails), `chunk_text`, `add_kb_chunk`,
  the `internet_search`/`SearchRunner` + `LLMCompleter` seams.

## How to verify
- `cd backend && .venv/bin/python -m pytest tests/test_learning_resources.py tests/test_crawl.py -q`
- Off request path: `grep -rn "discover_learning_resources\|mine_learning_resources" app/api app/services` → none.
- CLI (live DB/keys): `python -m app.tasks.learning_resources --skill Kubernetes --skill Python`.

## Tests (final step — mandatory)
- Full suite: `.venv/bin/python -m pytest -q` → **582 passed, 57 skipped** (was 550+; +21 new; skips
  unchanged = live-DB/ML). No failures.
- `.venv/bin/ruff check` (all new files + celery_app) → All checks passed; `ruff format --check` → clean.
- `.venv/bin/mypy app/ingestion/crawl.py app/ingestion/learning_resources.py
  app/repositories/learning_resources.py app/tasks/learning_resources.py` → Success, no issues.
  (CI type-checks `app/ migrations/` only; the test-double `arg-type` notes on concrete
  `RobotsChecker`/`HostRateLimiter` params match the existing `test_market_agent.py` convention and
  are not in CI scope.)

## Self-check
- [x] Meets acceptance criteria: testable core with fake search/http/LLM/DB (no live network);
      every fetch through the SSRF guard; `source_policy` imported/reused not re-implemented; page
      fenced + forced-tool extraction; persisted shared (`user_id IS NULL`) + skill-keyed `meta`
      answerable via `list_resources_for_skill`; Celery task with `refreshed_at` TTL, not called
      synchronously; unit tests cover normalization shape, robots/rate-limit/SSRF reuse, and
      idempotent re-run (URL dedup + delete-before-insert).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (DB via repo helper +
      `add_kb_chunk`; pipeline injects collaborators; crawling Celery-only).
- [x] Tests/lints pass (pasted above).
