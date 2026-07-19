---
name: check-guest-ephemeral-personalization
description: Reviewing P9-07-style guest session-only (Redis) personalization + upgrade-to-Postgres migration tasks
metadata:
  type: project
---

Reviewing the guest ephemeral-personalization seam (P9-07): guests get within-conversation
adaptation stored **Redis-only** (`RedisGuestMemory` over the `StoreRedis` seam, keyed by
`session_id`, TTL = guest-session lifetime), recalled by `agents/memory_agent.py::_recall_guest`,
learned by `memory/guest_personalization.py::GuestPersonalizationLearner`, and migrated to Postgres
on account upgrade by `GuestPersonalizationMigrator` (wired into `GuestUpgradeService`).

**Why:** two live risks — (1) an ephemeral memory becoming durable **unfiltered** on upgrade, and
(2) the guest path accidentally hitting Postgres before upgrade. Both are security/privacy gates.

**How to apply — check on every guest-personalization task:**
- **PII/Art. 9 gate reused, not duplicated, on BOTH write sides.** The `learn` write to Redis AND
  the upgrade migration must each call `memory/learn.py::gate_candidate` (redact contact PII → drop
  Art. 9). Confirm the migration re-gates even though Redis "already gated" (defense-in-depth). The
  convincing test seeds Redis directly past the learn gate then asserts a special-category memory
  does NOT reach the durable writer.
- **Guest recall must never touch Postgres.** `_recall_guest` runs only when `user_id is None`;
  assert the durable path is untouched (a `FakeSession([])` with no statements executed). Guest
  learn writes Redis only — assert no `add_memory`/Postgres call.
- **Fail-soft + best-effort everywhere.** Recall degrades to empty `MemoryContext` on Redis error;
  learn swallows extractor/store errors; migration failure must **never** break the upgrade/login
  (mirror `_backfill`'s try/except-log posture). The guest learn is fire-and-forget
  (`ChatService._spawn_guest_learn`, `asyncio.ensure_future` + strong task-ref set + done-callback);
  confirm it handles no-running-loop (`coro.close()`) and is gated on `assistant.content` + skipped
  on the cancelled path. Logged-in enqueue vs guest learn are mutually exclusive on `user_id`.
- **Known-acceptable nits (don't gate):** `RedisGuestMemory.record` is a non-atomic read-modify-write
  (two overlapping background learns can lose a memory — ephemeral, documented); the migrator
  `return`s on first per-memory write failure (drops the rest of the batch — best-effort). Flag as
  nits only.
- TTL: reuse/mirror the guest-session lifetime (`GUEST_MEMORY_TTL_SECONDS` default 86400 mirrors
  `GUEST_SESSION_TTL_SECONDS`) so personalization never outlives the session; TTL refreshed (sliding)
  on each write. TTL-expiry test uses a fake KV whose `get` returns None for a lapsed key → empty.
