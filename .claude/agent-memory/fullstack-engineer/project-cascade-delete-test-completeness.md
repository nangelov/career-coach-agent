---
name: project-cascade-delete-test-completeness
description: GDPR/cascade-delete tests must prove no orphan rows across EVERY child + grandchild table, not just top-level user-owned ones
metadata:
  type: project
---

A `delete_user`/erasure "no orphan rows" test must assert **zero surviving rows in every** table
the seed touches — direct user-owned tables *and* grandchildren reached only via a parent FK —
not just the obvious top-level ones. SEC-05's original cascade test seeded ~14 tables but only
asserted 5 were empty; SEC-09 verification flagged the other ~9 as under-proven.

**Why:** "cascade completeness" is the whole GDPR erasure guarantee (design §7.6). Asserting a
subset lets a broken/removed FK on an unchecked table (e.g. `messages`, `kb_chunks`, `milestones`,
`tasks`) silently leave PII behind.

**How to apply:**
- Direct user-owned tables: `select(func.count()).select_from(M).where(M.user_id == uid)` == 0
  (a small `_owned(M, uid)` helper keeps it DRY).
- Grandchildren with no `user_id`: join to the parent and filter on the parent's `user_id`
  (Message→Conversation, KbChunk→KbDocument, Milestone/DashboardTask→Goal).
- First confirm each FK's `ondelete`: content-bearing tables must be `CASCADE` (count==0 truly
  proves deletion). A `SET NULL` table (e.g. `feedback` — product feedback outlives the account)
  is intentionally *retained*, so don't assert it's gone — assert its PII columns are scrubbed
  instead (see [[project-session-registry-authority]]).
- This live-DB test skips without Postgres; bring infra up to actually run it — see
  [[project-live-docker-stack]] / the `test-integration` make targets.
