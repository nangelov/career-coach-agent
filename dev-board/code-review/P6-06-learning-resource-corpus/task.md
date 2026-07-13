# Task P6-06-learning-resource-corpus — Coursera/Udacity/Udemy/edX corpus
- **Phase:** P6   **Status:** ENG   **Tags:** (B)
## Scope
tasks.md P6 bullet 8 / plan.md P6 bullet 8: **Learning-resource corpus** (design §5.7): crawl Coursera /
Udacity / Udemy / edX (and similar) → normalized (title, provider, level, duration, cost, URL, **skills
covered**), **skill-keyed**, shared (`kb_documents.user_id IS NULL`), embedded into `kb_chunks`, TTL-refreshed
via Celery. Prefer official catalogs/APIs over scraping marketing pages. Will be cited by P7's PDP (not this
task's job to wire the citation — just make the corpus queryable/skill-keyed for it).

This is a **sibling, independent pipeline** to P6-04's market-intel mining (same shape, different corpus) —
**reuse its already-landed building blocks rather than reinventing them:**
- **Search/discovery**: the P6-03 `internet_search` tool / `TavilyPool` (same tool, different queries — e.g.
  `"<skill> course site:coursera.org"`).
- **Source policy**: `app/ingestion/source_policy.py` (`RobotsChecker` + `HostRateLimiter`, landed in P6-04) —
  **import and reuse this module**, do not re-implement robots.txt/rate-limiting.
- **Crawl transport**: `app.net.ssrf_guard.build_guarded_client` / `read_capped` (same SSRF-guarded client
  pattern `agents/web_searcher.py` and `agents/market_agent.py` use).
- **Untrusted content**: crawled course pages are external data (§7.3) — fence via
  `app.guardrails.untrusted_content.fence_untrusted` before any LLM extraction call; extraction uses a
  forced/constrained tool schema (mirror `market_agent.py`'s `_extract_requirements` pattern), never free-text
  parsing.
- **Persistence**: normalize each discovered resource to `{title, provider, level, duration, cost, url,
  skills: list[str]}`, store as a `kb_documents` row (`user_id IS NULL`, `source_type="curated"` — same
  vocabulary choice `market_agent.py` made for its normalized role-profile summaries, not raw `"crawled"`) with
  the normalized fields in `meta` JSONB (so `skills` is queryable/joinable — "skill-keyed" per §5.7), and embed
  a short descriptive chunk via `app.repositories.vector_search.add_kb_chunk` so hybrid search over the shared
  KB can surface it. **No new migration needed** — reuses the existing P2 `kb_documents`/`kb_chunks` schema.

Build as a Celery task (`app/tasks/learning_resources.py`, mirrors `tasks/market.py` / `tasks/taxonomy.py`'s
thin-wrapper-over-testable-core shape) with an explicit TTL/staleness marker in `meta` (e.g. `refreshed_at`) so
a periodic refresh can re-crawl stale entries; **never triggered from a user-facing request** (§7.5 — mining is
always a Celery job).

## Acceptance criteria
- [ ] A pipeline module (e.g. `app/ingestion/learning_resources.py` or `app/agents/` if it needs LLM extraction
      wiring — follow whichever precedent fits, consistent with how `market_agent.py`/`taxonomy_seed.py` split
      "testable core" from "Celery wrapper") discovers + normalizes + persists resources for a given skill or
      skill list, unit-testable with fake search/http/LLM dependencies (no live network in tests).
- [ ] Every fetch goes through the SSRF guard; `app/ingestion/source_policy.py` (`RobotsChecker`/
      `HostRateLimiter`) is imported and reused, not reimplemented.
- [ ] Course page text is fenced as untrusted before any LLM call; extraction is forced-tool-call, not
      free-text parsing.
- [ ] Persisted resources land in `kb_documents`/`kb_chunks` with `user_id IS NULL`, carrying `skills` in
      `meta` so a later query "resources covering skill X" is answerable (a simple JSONB containment / `meta
      ->> 'skills'` query or a helper function is enough — no new index/migration required for this task).
- [ ] A Celery task wraps the pipeline (`tasks/learning_resources.py`), with a TTL/`refreshed_at` marker;
      nothing calls it synchronously from a request path.
- [ ] Unit tests cover: normalization shape, SSRF/robots/rate-limit reuse (can be a thin
      "imports and calls the shared checker" test — the exhaustive robots/SSRF behavior itself is already
      tested in P6-04, don't duplicate that test surface), and idempotent re-run (re-crawling a known resource
      updates rather than duplicates — dedupe key = normalized URL is reasonable).

## Design references
- dev-board/plan.md: Phase 6, bullet 8  ·  dev-board/app-design-and-features.md §5.7 (full paragraph),
  §6 decision 20
- Reuse: `app/tools/internet_search.py` (Tavily-backed), `app/ingestion/source_policy.py`,
  `app/net/ssrf_guard.py`, `app/guardrails/untrusted_content.py`, `app/repositories/vector_search.py`
  (`add_kb_chunk`), `app/agents/market_agent.py` (sibling pipeline shape/precedent — read it for the pattern,
  do not import market-specific internals)

## Constraints / non-goals
- Do not touch `role_profiles`/`job_postings` or `agents/market_agent.py` — disjoint corpus, disjoint files
  (P6-04 already landed and is DONE; this task must not modify it).
- Do not wire PDP citation logic here — that is P7's job; this task only makes the corpus exist and be
  skill-queryable.
- Prefer official catalogs/APIs where practical; if only marketing-page crawling is feasible in this
  environment (no real provider API keys available), a documented Tavily-search + crawl + normalize pipeline
  is acceptable — note the upgrade path to official APIs in the module docstring, same posture as P6-01's
  taxonomy fixture note.
