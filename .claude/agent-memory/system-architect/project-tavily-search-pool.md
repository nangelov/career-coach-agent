---
name: project-tavily-search-pool
description: Blessed P6-03 Tavily 3-key search-provider pattern — placement, reuse of llm router infra, degradation; for P6-04/06/07
metadata:
  type: project
---

P6-03 landed the Tavily search-provider primitive (§5.7/§6.19), replacing SearXNG (`SEARXNG_URL` removed). APPROVED rev 1.

Blessed rulings (apply to later P6 mining/crawl tasks):
- **Placement**: `app/tools/tavily_pool.py` (not `app/net/`) — the concrete provider primitive is cohesive with its sole consumer `InternetSearchTool`; it only *reuses* `llm/` infra, it is not general net infra. Task sanctioned either location.
- **Reuse, don't reinvent**: `CircuitBreaker` + `RedisLike` imported verbatim from `llm/router.py` (`key_prefix="tavily:cb"`, keyed on **pool index**, never the raw secret). Do NOT write a second breaker/Redis seam. Promote-to-primary persisted at `tavily:primary_index`.
- **4xx semantics differ from LLM router (correct)**: a Tavily quota/auth 4xx DOES fail over to the next key (different secrets); the LLM router treats 4xx as non-failover. Per-key failover is right for a key pool.
- **Redis-optional degradation** is blessed: no Redis ⇒ in-call failover only, promotion/cache/breaker become no-ops. Wire the shared Redis client at the composition root (`bootstrap.build_chat_service`), not per-request.
- **Cache**: short-TTL Redis result cache with explicit constant (`SEARCH_CACHE_TTL_SECONDS`); full mining-result caching belongs to P6-04/07, crawl to P6-06 — keep those out of the provider task.
- Logged minor follow-up: `tools/registry.py` builds the tool redis-less; fine as graceful degradation, thread Redis there if a real caller resolves via the registry.

**Why:** keeps the Tavily reliability layer a single mechanism shared with §6.6, avoids a divergent breaker.
**How to apply:** when reviewing P6-04/06/07, expect them to *call* `TavilyPool`/`InternetSearchTool`, not add a parallel search/failover mechanism; caching/crawl is Celery-side, never a user turn.
See [[project-ci-posture]] for the skip-not-fail live-dependency test posture (Tavily tests use fakes, no network).
