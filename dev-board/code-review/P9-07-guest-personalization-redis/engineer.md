# Engineer report — P9-07-guest-personalization-redis · Revision 1

## Summary
Gives guests the same within-conversation adaptation logged-in users get (P9-02/03/06), but
**ephemeral, Redis-only, never durable** — and makes account upgrade (P3-03) carry that
ephemeral personalization into Postgres. New Redis-backed guest store (prefs + bounded memory
strings, keyed by `session_id`, TTL = guest-session lifetime); guest recall reads it; a
fire-and-forget in-process guest-learn writes to it (reusing the P9-03 extractor + P9-04
PII/Art. 9 gate); upgrade migrates it durably (re-gated). No responder change, no frontend work.

## Files changed
- `app/services/guest_memory.py` (NEW) — `GuestPersonalization` model + `GuestMemory` ABC +
  `InMemoryGuestMemory` double + shared `_merge_memories` (dedupe/cap).
- `app/repositories/redis.py` — `RedisGuestMemory` adapter (single JSON blob, sliding TTL,
  bounded list) over the existing `StoreRedis` seam; `Mapping` import.
- `app/repositories/__init__.py` — export `RedisGuestMemory`.
- `app/config.py` — `GUEST_MEMORY_TTL_SECONDS` (mirrors guest-session lifetime) +
  `GUEST_MEMORY_MAX_MEMORIES`.
- `app/memory/learn.py` — expose the write-boundary gate as public `gate_candidate` (was
  `_gate_candidate`) so the guest paths reuse the *same* PII/Art. 9 rule (no duplication).
- `app/memory/guest_personalization.py` (NEW) — `GuestPersonalizationLearner` (post-turn Redis
  learn) + `GuestPersonalizationMigrator` (upgrade Redis→Postgres) + narrow `DurableMemoryWriter`
  port.
- `app/agents/memory_agent.py` — `recall` / `make_memory_recall_node` extended with a guest path
  (reads `GuestMemory`); guest branch factored to `_recall_guest`; fail-soft preserved.
- `app/agents/graph.py` — thread `guest_memory` through `build_graph` / `GraphTurnStreamer` /
  `stream_graph`; recall node resolves when either backing (db **or** guest store) is bound.
- `app/services/chat.py` — `GuestLearner` port + `_spawn_guest_learn` (fire-and-forget
  `asyncio` task so the LLM extraction never delays the stream; done-callback drops the ref +
  logs escaped errors).
- `app/services/guest_upgrade.py` — optional `GuestPersonalizationMigrator` injected; new
  `_migrate_personalization` step (best-effort, mirrors `_backfill`'s fail-soft posture).
- `app/bootstrap.py` — wire `RedisGuestMemory` into the recall graph + a `GuestPersonalizationLearner`
  into `ChatService` (Redis-only, unconditional); build the migrator (Postgres-gated) into
  `build_guest_upgrade_service`.
- Tests: `test_guest_memory.py` (NEW), `test_guest_personalization.py` (NEW), extended
  `test_memory_agent.py`, `test_guest_upgrade_service.py`, `test_chat_persistence.py`.

## Key decisions
- **Separate store, not overloaded `SessionMemory`** (task hint) — new `GuestMemory` port +
  Redis adapter in the repository layer, same interface-before-implementation idiom as the
  sibling stores. Services never touch a Redis driver (§8 layering).
- **Memories stored as plain strings** (per acceptance-criteria wording) — dedup case-insensitively
  (first wins, stable order/casing) + cap oldest-first. On migration each string → `add_memory`
  with a default `memory_type="fact"` + `LearnConfig.default_confidence` (documented minor
  fidelity loss acceptable for ephemeral data).
- **Reuse, not duplicate, the P9-04 gate** — extracted `gate_candidate` is the single home; both
  the ephemeral write **and** the upgrade migration run it (defense-in-depth: an Art. 9 memory is
  dropped even though it "was already in Redis").
- **Guest learn runs in-process, fire-and-forget** — Celery isn't needed for a Redis write, but
  the extraction is an LLM call, so it's scheduled as a background `asyncio.Task` to honor the same
  "must not delay/break the stream" contract the logged-in enqueuer has. Guest vs logged-in learn
  are mutually exclusive per turn (keyed on `user_id`).
- **Preferences slot**: the store/migration support explicit preferences (migrated guest-wins-merge
  into the `preferences` row) for shape-parity with `MemoryContext` and to satisfy the upgrade
  criterion; the current guest *learn* step only writes memories (no guest pref-setting product
  flow) — documented, and the migration is exercised by seeding the store in tests.
- **Migrator as a collaborator** injected into `GuestUpgradeService` (SoC — keeps that service
  focused on transcript carry-over); best-effort so a migration failure never breaks login.

## How to verify
- `make lint` · `make typecheck` · `make test-integration` (full suite against docker Postgres).
- Guest recall: `test_memory_agent.py::test_guest_recall_reads_redis_personalization`.
- Guest learn writes Redis only + gate: `test_guest_personalization.py` (writes-to-redis, redacts
  PII, drops special-category, fail-soft).
- TTL expiry: `test_guest_memory.py::test_redis_expired_session_reads_back_empty`.
- Upgrade migrates + re-gates + clean no-op: `test_guest_personalization.py` migrator tests +
  `test_guest_upgrade_service.py::test_upgrade_migrates_guest_personalization` /
  `..._migration_failure_does_not_break_upgrade`.
- Guest turn spawns learn, logged-in does not: `test_chat_persistence.py` guest-learn tests.

## Tests (final step — mandatory)
- `make test-integration` → **940 passed, 1 skipped** in 17.19s (the skip is a pre-existing
  conditional, not introduced here).
- `make lint` → All checks passed. `make typecheck` → Success, no issues in 156 source files.
- No failures to root-cause. (During development two of my own new store tests asserted a dedup
  policy that didn't match the chosen "first-occurrence-wins" semantics; I aligned the store's
  `_merge_memories` to the simpler/stable first-wins policy and corrected the test expectations —
  the store behavior is the source of truth, documented in its docstring.)

## Self-check
- [x] Meets acceptance criteria (Redis store; guest recall; guest learn Redis-only + gate; never
  touches Postgres pre-upgrade; upgrade migrates prefs+memories through the gate, best-effort;
  full unit-test coverage incl. TTL expiry + no-op upgrade).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (port in `services/`,
  Redis adapter in `repositories/`, wiring in `bootstrap.py`).
- [x] Tests/lints/types pass (pasted above). Locked decisions honored (Redis+Postgres only; native
  tool-calling extractor reused; free/OSS).
