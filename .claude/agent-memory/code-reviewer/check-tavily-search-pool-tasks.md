---
name: check-tavily-search-pool-tasks
description: Reviewing P6-03 Tavily 3-key rotating search pool (tools/tavily_pool.py) — reuse of llm/router CircuitBreaker+RedisLike, secret-in-header-not-key, response.json() escaping the httpx.HTTPError failover catch
metadata:
  type: project
---

Reviewing the Tavily search-provider pool (`backend/app/tools/tavily_pool.py`, behind `internet_search`, replacing SearXNG).

**Why:** P6-03 mandates reusing the §6.6 LLM-router failover machinery, not a second breaker. Search results are untrusted external data and keys are secrets.

**How to apply — checks that matter here:**
- **CircuitBreaker/RedisLike reuse:** must be *imported* from `app.llm.router`, keyed on pool **index** (`str(idx)`), never the raw key. Breaker key format is `<prefix>:<model>:open` / `:fails` — verify test fakes match (`tavily:cb:0:open`).
- **Secret hygiene:** key only in outbound `Authorization: Bearer` header; never in URL, log line, or Redis key. Tests should assert `secret not in captured["url"]` and `secret in captured["auth"]`.
- **Failover catch scope (recurring gap):** the per-key failover loop catches `httpx.HTTPError` (covers raise_for_status HTTPStatusError + TimeoutException). But `response.json()` raises stdlib `json.JSONDecodeError` (NOT httpx.HTTPError), so a malformed 2xx body escapes both the failover `continue` AND the adapter's `TavilyNotConfiguredError/TavilyPoolExhaustedError` mapping → uncaught, violating the tool's "run() returns ToolResult, never raises" contract. Flag as minor (unlikely body, but web_searcher line ~126 calls `search_tool.run()` un-wrapped and relies on `.is_error`).
- **Promotion:** persisted to `tavily:primary_index`; `_key_order()` reads it, clamps to valid range, tries promoted primary first. Verify a 2-call test proves cross-call promotion (not just in-call failover).
- **Cache:** short-TTL constant (`SEARCH_CACHE_TTL_SECONDS`), keyed on sha256 of normalized (lowercased/whitespace-collapsed) query + max_results; cache-hit short-circuits before the key loop (intended — saves quota even if keys down). Empty-result successes get cached (benign).
- **Redis-optional degradation:** no redis → in-call failover still works, promotion/cache/breaker become no-ops. Good posture; keep the lazy `from_settings()` default working while bootstrap injects the shared Redis client.
