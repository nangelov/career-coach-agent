---
name: project-idempotent-rescanned-signal
description: A background task that re-scans a standing signal (recent votes/events) each run must apply it idempotently per signal, or effects compound
metadata:
  type: project
---

A post-turn/background task that **re-scans a rolling window of a standing signal** (e.g.
`list_recent_downvotes`, recent events) on every run will **re-apply** that signal each pass until
it scrolls out of the window — compounding effects (e.g. confidence demotion 0.9→0.6→0.3→deleted,
silent data loss).

**Why:** the window contents don't change between runs, and there's no "already-processed" marker
by default. Reviewer flagged this as a major finding in P9-03 (thumb-down demotion).

**How to apply:** make the effect **idempotent per signal**. Cheapest fix when both sides carry a
server timestamp: gate on `target.updated_at > signal.created_at` (skip targets already touched in
response to that signal). Prefer strict `>` so a timestamp tie still applies once. Once the effect
writes the row (`onupdate=now()`), its timestamp lands past the signal → later passes skip; a fresh
re-signal bumps `created_at` and is honoured. Avoids a new column / processed-marker table. See also
[[project-pg-now-constant-in-txn]] (distinct txns give distinct now()).
