---
name: ruling-verify-live-pg-composition
description: Phase-exit verify tasks may run against live Postgres (not fully-offline P8-06 style) when the claim is that write/read/delete address the same durable rows
metadata:
  type: project
---

Blessed at P9-10-verify: a phase-exit verification suite may use **live Postgres** (skip-clean when unreachable, per the `*_persistence` precedent) rather than the fully-offline P8-06 fake-ports style — **when** the design claim being proven is that separate code paths address the *same durable rows*.

**Why:** P9's whole point is that learn (write), recall (read) and CRUD (delete) hit one `user_memories`/`preferences` table. Proving that over fakes would prove a shared dict, not a shared table — the composition is the thing under test, so it must run against the real store. Faking only the true external edges (8B embedder → fixed 4096-dim vector, extractor LLM → scripted candidates) keeps it budget/offline-safe.

**How to apply:** Don't flag live-PG posture as a deviation from P8-06 in a verify task, provided (a) it skips cleanly without a DB, (b) it fakes only the genuine external edges, and (c) the shared-row claim is the point. If the claim is purely logic-level (like P8-06's), expect fully-offline instead. See also [[ruling-session-memory-placement]] (store impls in repositories/, memory/ module is legit per §8).
