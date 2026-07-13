---
name: project-cache-first-async-mine-dupe-enqueue
description: Cache-first read + Celery-mine-on-miss endpoints (P6 roles/market) don't cache the miss, so cold roles re-run the embedder and re-enqueue duplicate expensive mine jobs
metadata:
  type: project
---

The P6 market/roles read endpoints follow a "cache-first read, enqueue a Celery mine on miss" shape (`RolesService.get_requirements`). Watch two recurring gaps here:

- **Cold (never-mined) roles are not cached** — a 202 carries no body, so nothing is cached. Every repeated request for the same unmined role re-runs canonicalization (the in-process sentence-transformers **embedder = CPU-heavy**) and calls `enqueue_mine(...)` again. There is no in-flight dedup/lock, so N concurrent requests for one cold role spawn N duplicate expensive crawl+LLM mine jobs — contradicting §5.6 "extraction paid once per role". Bounded only by rate limits. Suggested fix: a short-lived Redis "mine in-flight" marker keyed on canonical role.
- **Stale-refresh cache coherency** — a stale-but-served profile is cached for the full cache TTL AND a background mine is enqueued, but the completing mine does not invalidate the Redis cache, so stale data is served until the TTL lapses.

**Why:** these are resource-amplification / staleness smells, not correctness bugs — acceptable to APPROVE with notes at this phase, but flag them.
**How to apply:** on any new cache-first + async-mine/ingest endpoint (P6-08+, future market/learning-resource reads), check for miss-path dedup and post-job cache invalidation. Related: [[project-crawler-fetcher-ssrf]] (mining correctly kept OFF the request path here — verify that stays true).
