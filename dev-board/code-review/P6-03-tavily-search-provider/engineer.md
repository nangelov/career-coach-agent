# Engineer report — P6-03-tavily-search-provider · Revision 1

## Summary
Replaced the SearXNG search backend with **Tavily**, accessed through a **3-key rotating
pool** that fails over on a dead/exhausted key, **promotes the survivor to primary**
(persisted in Redis), circuit-breaks per key, and **caches results in Redis**. The pool
reuses the §6.6 LLM-router machinery (`CircuitBreaker` + `RedisLike`) rather than inventing a
second mechanism. The `internet_search` tool name/schema/`ToolResult` contract is unchanged,
so `agents/web_searcher.py` and every other caller keep working untouched.

## Files changed
- `app/tools/tavily_pool.py` (new) — `TavilyPool`: ordered pool over up to 3 keys, in-call
  failover, promote-to-primary (`tavily:primary_index`), per-key `CircuitBreaker`
  (`key_prefix="tavily:cb"`, keyed on pool **index**, never the secret), Redis result cache
  (`SEARCH_CACHE_TTL_SECONDS = 3600`). `TavilyNotConfiguredError` / `TavilyPoolExhaustedError`.
- `app/tools/internet_search.py` — now a thin adapter over `TavilyPool` (same schema/name);
  `from_settings(..., redis_client=None)`; maps pool errors to graceful `ToolResult.error`.
- `app/config.py` — added `TAVILY_API_KEY_1/2/3` (Space-secret-sourced, default `""`); removed
  the now-dead `SEARXNG_URL`. `SEARCH_TIMEOUT_SECONDS` kept.
- `app/bootstrap.py` — `build_chat_service` builds a redis-wired `InternetSearchTool` from the
  **shared** Redis client and injects it into `GraphTurnStreamer(search_tool=...)`, so the
  pool's promotion/cache/breaker use the one §4 pool.
- `app/agents/web_searcher.py`, `app/agents/graph.py` — updated stale SearXNG docstrings.
- `tests/test_tavily_pool.py` (new) — pool unit tests (normalize, failover+promotion,
  promoted-primary-first next call, open-circuit skip, caching, no-redis in-call failover,
  not-configured/exhausted).
- `tests/test_tools.py` — reworked the `internet_search` tests onto the Tavily pool + mock
  transport (secret asserted in the `Authorization` header, never in the URL).

## Key decisions
- **Location = `app/tools/`** (not `app/net/`): the pool is the concrete search-provider
  primitive behind the `internet_search` tool, cohesive with it (mirrors how the tool already
  owned its httpx concerns); it only *reuses* `llm/` infra pieces, it is not general net infra.
- **Reuse `CircuitBreaker` + `RedisLike` verbatim** (imported from `llm/router.py`) per §6.19 /
  task — no second breaker. Breaker/log keys use the pool index, so a raw key value is never
  logged or persisted (only ever in the outbound `Authorization: Bearer` header).
- **Redis optional**: without a Redis client the pool still does in-call failover; promotion,
  cache, and breaker become no-ops. Keeps the lazy `InternetSearchTool.from_settings()` default
  (web-search node) working, while production wires Redis via bootstrap.
- **Retired SearXNG** (design doesn't call for keeping it): removed `SEARXNG_URL` and its code
  path; kept the graceful "not configured" behavior when no key is set.
- **Cache key** = sha256 of normalized (lowercased, whitespace-collapsed) query + `max_results`.

## How to verify
- `cd backend && make test` (or `uv run --no-sync pytest`).
- Targeted: `uv run --no-sync pytest tests/test_tavily_pool.py tests/test_tools.py tests/test_web_searcher.py`.

## Tests (final step — mandatory)
- `uv run --no-sync pytest -q` → **521 passed, 57 skipped** (skips are live-DB integration
  tests; no Postgres in this run). No failures.
- `uv run --no-sync ruff check` (touched files) → All checks passed.
- `uv run --no-sync mypy app/tools/tavily_pool.py app/tools/internet_search.py app/bootstrap.py app/config.py app/agents/web_searcher.py app/agents/graph.py` → Success, no issues.

## Self-check
- [x] Meets acceptance criteria (Tavily via 3-key pool; failover+promotion unit-tested with
  fake Redis; `CircuitBreaker` reused/imported; `TAVILY_API_KEY_1/2/3` added, secrets never
  logged; callers unchanged, `test_web_searcher` green; Redis cache with explicit TTL constant).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (tools reuse llm infra;
  Redis wiring goes through the shared pool at the composition root).
- [x] Tests/lints pass (pasted above).
