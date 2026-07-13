---
name: pattern-market-intel-read-vs-mine-split
description: P6-04 market-intel blessed pattern — request-path read worker vs Celery mining split; shared source_policy; source_type=curated for aggregates
metadata:
  type: project
---

P6-04 market-intelligence conformance (design §5.6/§7.4/§7.5) — blessed patterns to keep consistent in P6-05/06/07:

**Read-vs-mine cost split.** `agents/market_agent.py` has two halves: `retrieve_market_intel`/`make_market_node`
(request-path MARKET_INTEL worker — *reads* cached shared KB `role_profiles`+taxonomy, **never crawls**, fails
soft like RAG) and `mine_role_requirements` (the taxonomy→crawl→extract→aggregate→persist pipeline, Celery-only
via `tasks/market.py`, never request-path per §7.5). Enrichment: retrieved summary chunks carry
`meta.canonical_role`, worker loads the structured `role_profiles` rows from that — no inline crawl.

**Shared source policy.** `app/ingestion/source_policy.py` (`RobotsChecker` + `HostRateLimiter`, stdlib
`urllib.robotparser`, injected fetch/clock/sleep) is the ONE reusable robots.txt+rate-limit module — P6-06
learning-resource crawl must import it, not duplicate. LinkedIn hard-deny composes with the SSRF guard via
`DEFAULT_DENY_HOSTS|{linkedin.com}` + `.linkedin.com` suffix (rejected pre-DNS), not a hand-rolled check.

**Why:** these are expensive-to-unwind seams (cost amortization, politeness policy, SSRF single-client rule).

**How to apply:** reject any P6 sibling that (a) crawls on the request path, (b) re-implements robots/rate-limit,
(c) hand-rolls a second guarded HTTP client, or (d) keys market data on `user_id` (role profiles are global).

**Minor accepted:** mined role-profile summary embedded into `kb_chunks` uses `source_type="curated"` (the
`ck_kb_documents_source_type` allows curated/user_cv/crawled only). Defensible — a synthesized aggregate is
curated, not raw crawled evidence — and adding a distinct value needs a migration. Blessed as-is. See
[[ruling-curated-ci-light-deps]] for the deferred-heavy-import convention this module also follows.
