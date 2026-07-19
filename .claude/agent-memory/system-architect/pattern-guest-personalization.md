---
name: pattern-guest-personalization
description: P9-07 blessed guest session-only personalization — Redis-only GuestMemory port, in-process asyncio learn, upgrade-time re-gated migration
metadata:
  type: project
---

P9-07 (guest personalization, §5.4) blessed pattern. **Why:** guests get within-conversation
adaptation but nothing durable without an account; upgrade persists it.

**How to apply** (for future guest/memory + upgrade-migration tasks):
- **Separate Redis store, not overloaded [[project-conversation-persistence]] SessionMemory**:
  `GuestMemory` ABC + `GuestPersonalization` model in `services/guest_memory.py`; `RedisGuestMemory`
  adapter in `repositories/redis.py` over the existing `StoreRedis` set/get seam — same
  port-in-services / adapter-in-repositories idiom as every other Redis store (NOT a layer
  inversion; this repo's convention). TTL mirrors guest session lifetime (sliding), memories capped.
- **Redis-only until upgrade** is the hard rule: guest learn writes only Redis; the ONLY Postgres
  path is `GuestPersonalizationMigrator` on successful upgrade.
- **Gate reuse (not reimplementation)**: the [[pattern-memory-learn-step]] P9-04 `gate_candidate`
  (PII redact + Art.9 drop) runs on the ephemeral write AND is re-run on migration
  (defense-in-depth — "already in Redis" does not exempt it). Extracting `_gate_candidate`→public
  `gate_candidate` for reuse is blessed.
- **Guest learn = in-process fire-and-forget asyncio task** (Celery reserved for durable jobs); must
  hold a strong task ref + done-callback, must never delay/break the SSE stream. Logged-in enqueuer
  vs guest learner are mutually exclusive per turn, keyed on `user_id`.
- **Migration**: prefs→`preferences` row (guest-wins merge), memories→`UserMemoryStore.add_memory`
  (reuse [[pattern-memory-recall-store]] store, don't hand-roll insert); best-effort, mirrors the
  transcript `_backfill` fail-soft posture so a migration failure never aborts login. String
  memories migrate as `memory_type="fact"` (accepted fidelity loss).
- Accepted minor: `repositories/redis.py` importing private `_merge_memories` from services (shared
  bound/dedup, DRY); promote to non-private only if store caps ever diverge.
