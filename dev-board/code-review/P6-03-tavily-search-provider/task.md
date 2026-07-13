# Task P6-03-tavily-search-provider — Tavily 3-key rotating search pool
- **Phase:** P6   **Status:** ENG   **Tags:** (B)
## Scope
tasks.md P6 bullet 7 / plan.md P6 bullet 7: **Tavily search provider + 3-key rotating pool** (§5.7 / §6.19):
`TAVILY_API_KEY_1|2|3` from Space Secrets; ordered failover, **promote the surviving key to primary**
(persisted in Redis so a dead/exhausted key isn't retried every call), quota-aware. **Reuse the
`llm/router.py` failover pattern — do not invent a second mechanism.** Replaces the current search backend in
`tools/internet_search.py`.

**What exists today:** `backend/app/tools/internet_search.py` implements the `internet_search` tool against a
self-hosted SearXNG instance (`Settings.SEARXNG_URL`), a P1 implementation choice — the design's locked P6
decision supersedes it with Tavily as the search provider. `backend/app/llm/router.py` has a reusable
`CircuitBreaker` class (Redis-backed, generic over any string key, `key_prefix` configurable) — **reuse this
class directly** (instantiate with `key_prefix="tavily:cb"`) rather than writing a second circuit-breaker.

Build:
1. `app/config.py`: add `TAVILY_API_KEY_1`, `TAVILY_API_KEY_2`, `TAVILY_API_KEY_3` (each `str`, default `""`,
   Space-secret-sourced) settings, following the existing `Settings` field style.
2. A Tavily client/pool module (e.g. `app/tools/tavily_pool.py` or `app/net/tavily_pool.py` — pick a location
   consistent with whether this is "a tool" vs "infra" and justify it in `engineer.md`) implementing:
   - An **ordered pool** of up to 3 keys (skip blank ones).
   - **Failover**: on a request failure (HTTP error, timeout, Tavily quota/auth error), try the next key in
     order within the same call.
   - **Promote-to-primary persisted in Redis**: once a key other than index 0 succeeds, remember it (a Redis
     key, e.g. `tavily:primary_index`) so subsequent calls start from the surviving key instead of always
     retrying the dead one first. Use the injected `RedisLike`-style protocol already defined in
     `llm/router.py` (reuse it, do not redeclare) so this stays testable without a live Redis.
   - Reuse `CircuitBreaker` per key (`key_prefix="tavily:cb"`, keyed by key-index or a stable key id, never by
     the raw secret value) so a recently-failing key is skipped for a cooldown window like the LLM router does.
3. Rewire `tools/internet_search.py` to call the Tavily pool as its **primary/only** provider for the
   `internet_search` tool schema (same tool name/schema/`ToolResult` contract — callers in `agents/web_searcher.py`
   and elsewhere must not need changes). Keep the tool's graceful "not configured" result when no Tavily key is
   set at all (mirrors the current `SEARXNG_URL` empty-string behavior). You may retire the `SEARXNG_URL` /
   `SearXNG`-specific code path (design doesn't call for keeping it) — if you do, remove the now-dead
   `Settings.SEARXNG_URL` field and update its docstring/tests; if you keep it as a fallback, document why.
4. Redis-cache raw search results (design §5.7: *"cache search results in Redis... never let a user-facing turn
   trigger uncached crawling"*) — a short-TTL cache keyed on the normalized query is enough here; do not
   over-build (full mining-result caching is P6-04/P6-07's job).

## Acceptance criteria
- [ ] `internet_search` tool (same name/schema) now queries Tavily via the 3-key pool; unit tests inject a fake
      HTTP transport / fake Tavily client so no real network call happens.
- [ ] Failover across keys is unit-tested: key 1 fails → key 2 succeeds → subsequent calls start at key 2
      (promotion persisted via a fake/in-memory Redis-like double).
- [ ] `CircuitBreaker` from `llm/router.py` is reused (imported), not reimplemented.
- [ ] `Settings` gains `TAVILY_API_KEY_1/2/3`; secrets never logged.
- [ ] `agents/web_searcher.py` and any other `internet_search` caller keep working unchanged (same `ToolResult`
      shape) — run its existing test suite to confirm no regression.
- [ ] Basic Redis caching of search results is in place with an explicit TTL constant.

## Design references
- dev-board/plan.md: Phase 6, bullet 7  ·  dev-board/app-design-and-features.md §5.7 ("Search provider →
  Tavily..."), §6 decision 19
- Reuse: `backend/app/llm/router.py` (`CircuitBreaker`, `RedisLike` protocol, failover/promotion pattern)
- Existing tool contract: `backend/app/tools/internet_search.py`, `backend/app/tools/base.py`

## Constraints / non-goals
- Do not build the learning-resource crawl here (P6-06) or the market-posting mining here (P6-04) — this task
  only lands the **search provider primitive** both will call.
- No live Tavily account/keys are available in this environment — all tests must run against fakes/mocks; do
  not attempt a real network call in tests or CI.
