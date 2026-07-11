---
name: ruling-web-searcher-p6-scope-split
description: P4-05 web-searcher legitimately defers §3's structured role-page extraction + Postgres write + Celery to P6
metadata:
  type: project
---

The §3 "Web Searcher + Crawler" bullet bundles two responsibilities that are split across phases:

- **P4-05 (chat-graph worker):** general internet search + a small, bounded, *synchronous* per-turn crawl of
  a few top hits → inert grounding text + `Citation`s for the responder. No datastore write, no Celery, no
  structured schema. stdlib `html.parser` (no bs4/selectolax dep) is blessed for extraction on §11 budget
  grounds.
- **P6 (structured role-page pipeline):** the §3 clauses *"crawls job-profile/role pages to extract
  structured info (skills, requirements)"* and *"Writes findings to Postgres for reuse"* — normalized job/role
  schema + Postgres persistence + async Celery crawl.

**Why:** foundation-first sequencing — the chat graph needs a working search worker now; the heavier
extraction/persistence pipeline is its own phase.

**How to apply:** do NOT flag P4-05 for missing the Postgres-write / structured-extraction half of §3 — it is
intentionally P6. DO expect P6 to close that loop. Inline bounded crawl in the chat graph is the right
granularity and must not pre-couple to the P6 Celery path. See [[pattern-worker-node-di-scope]] — note the
access-scoping allow-list rule does NOT apply to the web searcher (public web, no user-scoped store); it
still applies to the P4-06 job/PDP workers, which touch user CV data.
