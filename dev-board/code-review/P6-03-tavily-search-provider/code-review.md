# Code review — P6-03-tavily-search-provider · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | app/tools/tavily_pool.py:200-201 | The per-key failover loop catches `httpx.HTTPError` (covers `raise_for_status` and timeouts), but `response.json()` raises stdlib `json.JSONDecodeError`, which is **not** an `httpx.HTTPError`. A malformed 2xx body (e.g. an HTML error page from a proxy/CDN returned with 200) therefore escapes both the loop's `continue` and `InternetSearchTool.run`'s `TavilyNotConfiguredError/TavilyPoolExhaustedError` mapping, so `run()` raises instead of failing over / returning a graceful `ToolResult.error` — violating the tool's stated "never crash the call loop" contract (web_searcher.py:126 calls `search_tool.run()` un-wrapped and only inspects `.is_error`). Wrap the `.json()`/parse so a decode error is treated as a key failure (record_failure + continue) or at least mapped to the graceful adapter path. Unlikely payload, so non-gating. |
| C2 | nit | app/tools/tavily_pool.py:54 | `SEARCH_CACHE_TTL_SECONDS = 3600` (1h) is defensible but on the long side for the "short-TTL" the task/§5.7 describes; fine as-is, worth a comment if intentionally 1h. |

## Notes
- Acceptance criteria all met: Tavily 3-key pool behind the unchanged `internet_search` name/schema/`ToolResult` contract; failover + promote-to-primary persisted via fake Redis is unit-tested (`test_failover_promotes_survivor_to_primary`, `test_promoted_primary_is_tried_first_on_next_call`); `CircuitBreaker`/`RedisLike` are **imported and reused** from `llm/router.py` (not reimplemented), keyed on pool index; `TAVILY_API_KEY_1/2/3` added; Redis result cache with explicit `SEARCH_CACHE_TTL_SECONDS` constant.
- Security: verified secrets stay in the outbound `Authorization: Bearer` header only — never in the URL, log lines (log/breaker key on pool index), or Redis keys. Tests assert `secret not in url` / `secret in auth`, and that circuit-breaker keys use the index (`tavily:cb:0:*`, not the raw key). Breaker key format matches router (`<prefix>:<model>:open|:fails`).
- Untrusted-response handling in `_normalize` is defensive (isinstance-guards, string coercion, snippet truncation, `[]` on malformed shape) — no execution of external content.
- SearXNG fully retired: `SEARXNG_URL` removed from `Settings`; no lingering `base_url=`/SearXNG code paths in the tool or its callers (only unrelated `httpx.AsyncClient(base_url=...)` / OAuth `redirect_base_url` remain). Docstrings in graph.py/web_searcher.py updated.
- Bootstrap correctly injects a Redis-wired `InternetSearchTool` built from the shared Redis client into `GraphTurnStreamer(search_tool=...)`, so promotion/cache/breaker use the one shared pool; the import-time default stays lazy and Redis-less (graceful).
- Redis-optional degradation is sound (in-call failover works without Redis; promotion/cache/breaker no-op).
- Ran targeted suites: `pytest tests/test_tavily_pool.py tests/test_tools.py tests/test_web_searcher.py` → 41 passed. Caller (`web_searcher`) unchanged and green.
- Design-conformance (does this match the planned architecture / §5.7 / §6.19 and location choice) is the system-architect's call; noted only that `app/tools/` placement is justified in engineer.md.
- The working tree also contains unrelated uncommitted P6-01/P6-02 changes (market models, taxonomy, jobs.py deletion); out of scope for this review.
