# Architecture review — P6-03-tavily-search-provider · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Search provider = Tavily 3-key pool | §5.7 / §6.19: ordered pool over `TAVILY_API_KEY_1|2|3`, failover, promote-to-primary persisted in Redis, quota-aware | `TavilyPool` = ordered pool (blanks skipped), in-call failover, `_promote`→`tavily:primary_index`, `_key_order` starts from promoted primary | none |
| A2 | Reuse §6.6 router machinery, no 2nd mechanism | §6.19 "reuse that pattern rather than inventing a second one" | `CircuitBreaker` + `RedisLike` imported verbatim from `llm/router.py` (`key_prefix="tavily:cb"`, keyed on pool index) | none |
| A3 | Cache results in Redis | §5.7/§11: cache in Redis, never let a user turn trigger uncached crawling | sha256(normalized query + max_results) cache, explicit `SEARCH_CACHE_TTL_SECONDS=3600`; crawl/mining correctly deferred to P6-04/06 | none |
| A4 | §8 module placement | infra vs tool seam | Placed in `app/tools/` next to sole consumer `InternetSearchTool`; reuses `llm/` infra without depending on `agents`/`services` | acceptable — task sanctioned either location; justification is sound |
| A5 | Layering (tool→llm infra) | Router→Service→Agent/Repo; no cross-layer leak | `tools` depends only on the `llm/` CircuitBreaker/RedisLike seam (a lower-level infra primitive the design tells it to reuse); Redis wired at composition root (`bootstrap.py`), not per-request | none |
| A6 | Contract unchanged for callers | tool name/schema/`ToolResult` stable so `agents/web_searcher.py` etc. untouched | `internet_search` schema/name unchanged; thin adapter maps pool errors to graceful `ToolResult.error`; web_searcher/graph only got docstring edits | none |
| A7 | Config + secrets | §6.19 Space-secret-sourced keys; secrets never logged | `TAVILY_API_KEY_1/2/3` added (default `""`); dead `SEARXNG_URL` removed; keys only ever in outbound `Authorization` header, breaker/logs key on index | none |
| A8 | Budget posture | §11: free/OSS/self-hosted | Tavily free tier, in-process pool, shared self-hosted Redis; no paid tier | none |
| A9 | Phase fit | P6 lands the search **primitive** only | Provider + pool only; mining (P6-04) and learning-resource crawl (P6-06) explicitly out of scope | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (tool reuses llm infra at composition root)
- [x] Honors locked decisions (Tavily §6.19; Postgres+Redis only; reuses §6.6 router pattern)
- [x] Interfaces-before-implementations (`RedisLike`/`CircuitBreaker` seams reused; `TavilyPool` injectable http/redis for tests)
- [x] Budget posture respected (free/OSS/self-hosted)

## Notes
- Correct design distinction vs the LLM router: a Tavily `4xx` (quota/auth) here **does** fail over to the next key (different secrets), whereas the router treats 4xx as non-failover. This is the right per-key semantics and satisfies "quota-aware" — a dead/exhausted key trips its own breaker and is skipped.
- Minor follow-up (not blocking): `tools/registry.py` still builds `InternetSearchTool.from_settings(config, http_client=...)` **without** `redis_client`, so a registry-sourced tool runs redis-less (in-call failover only; no promotion/cache/breaker). The production chat path is correctly redis-wired via `bootstrap.build_chat_service`, so this is graceful degradation per the pool's documented no-redis mode, not a violation. If any real caller resolves the tool through the registry, thread the shared Redis client there too in a later pass.
- Promotion + cache degrade to no-ops without Redis by design — consistent with §4 "guests/Redis-optional" posture and the router's own no-datastore-dependency stance.
