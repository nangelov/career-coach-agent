# Architecture review — P9-07-guest-personalization-redis · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure / layering | Port ABC in `services/`, Redis adapter in `repositories/`, learn/migrate logic in `memory/`, wiring in `bootstrap.py` | `GuestMemory` ABC + `GuestPersonalization` model + double in `services/guest_memory.py`; `RedisGuestMemory` adapter in `repositories/redis.py`; `GuestPersonalizationLearner`/`Migrator` in `memory/guest_personalization.py`; wired in `bootstrap.py` | None — matches the established port-in-services / adapter-in-repositories idiom (SessionMemory, SessionStore, RateLimiter precedent) |
| A2 | §5.4 guest ephemerality | Personalization Redis-only, never durable pre-upgrade | Guest learner writes only to `GuestMemory` (Redis); `RedisGuestMemory` uses the `StoreRedis` set/get seam; no Postgres path outside the migrator | None |
| A3 | §5.4 recall shape-parity | Guest recall yields same `MemoryContext` (prefs+memories) so responder (P9-06) is unchanged | `_recall_guest` returns `MemoryContext(preferences, memories)`; responder untouched | None |
| A4 | §5.4 upgrade persists | Guest→account migrates prefs→`preferences` row, memories→`UserMemoryStore.add_memory` | `GuestPersonalizationMigrator.migrate` via injected `PreferenceStore` + `DurableMemoryWriter`; reuses P9-05 stores, no hand-rolled insert | None |
| A5 | §7.6 PII/Art.9 gate reuse | Same gate on ephemeral write AND migration; no reimplementation | `_gate_candidate` promoted to public `gate_candidate`, single home; run in learner and re-run in `_migrate_memories` (defense-in-depth) | None |
| A6 | §4 datastore posture | Postgres + Redis only; TTL bounded to guest session lifetime | New `GUEST_MEMORY_TTL_SECONDS` (default 24h mirroring guest session), sliding; `GUEST_MEMORY_MAX_MEMORIES` cap | None |
| A7 | Best-effort fail-soft | Migration failure must not break upgrade; guest learn must not delay stream | `_migrate_personalization` mirrors `_backfill` fail-soft; `_spawn_guest_learn` fire-and-forget asyncio task with strong-ref set + done-callback | None |
| A8 | Locked decisions | native tool-calling extractor, in-process embeddings, no Mongo | Reuses `LLMMemoryExtractor(llm_router)`, `SentenceTransformerEmbeddingClient`; Redis+Postgres only | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — services depend only on the `GuestMemory` ABC; the Redis driver stays behind the repository adapter.
- [x] Honors locked decisions (no ReAct parser; Postgres+Redis only; SSO-only untouched; in-process embeddings; native tool-calling extractor reused).
- [x] Interfaces-before-implementations (`GuestMemory` ABC + `DurableMemoryWriter` Protocol; `GuestLearner`/`LearnEnqueuer` ports on the chat service).
- [x] Budget posture respected (free/OSS/self-hosted; no new external deps).

## Notes
- **Minor (log, not blocking):** `repositories/redis.py` imports the private `_merge_memories` from `services/guest_memory.py`. Cross-module import of an underscore-prefixed helper is a small encapsulation nit; it is deliberate to keep the bound/dedup behavior byte-identical between the in-memory double and the Redis adapter (a legitimate DRY goal). If either store's caps ever diverge, promote it to a non-private shared helper. No action required now.
- **Preferences slot has no current producer:** guest *learn* writes only memories; the preferences path exists for `MemoryContext` shape-parity and the upgrade-migration criterion, and is exercised via seeded tests. This is spec-required (acceptance criteria demand prefs+memories migration), not YAGNI — accepted.
- **Guest learn = in-process asyncio (not Celery):** correct call per the task (ephemeral Redis write needs no durable job); documented, and the fire-and-forget task holds a strong ref + logs escaped errors. Consistent with the "never delay/break the stream" contract of the logged-in enqueuer.
- **Migration fidelity:** guest string memories migrate as `memory_type="fact"` at `default_confidence` — a documented, acceptable fidelity loss for ephemeral data that keeps the Redis shape a simple string list.
- Scope note: the `HEAD` diff also shows P9-01..P9-06 files (whole phase uncommitted); those are out of scope here and were not gated.
