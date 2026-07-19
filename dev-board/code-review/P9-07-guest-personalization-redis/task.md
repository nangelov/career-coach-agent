# Task P9-07-guest-personalization-redis — guest personalization is session-only (Redis)
- **Phase:** P9   **Status:** ENG   **Tags:** (B)

## Scope
Give **guests** the same within-conversation adaptation logged-in users get from P9-02/03/06 —
but ephemeral, Redis-only, never durable — and make **account upgrade** (P3-03) carry that
ephemeral personalization into the durable Postgres stores (`preferences` / `user_memories`).

From `dev-board/tasks.md` (P9):
> Guests: personalization session-only (Redis); account upgrade persists it.

### Current state (read before building)
- Recall (`backend/app/agents/memory_agent.py`, P9-02): for a guest (`state.user_id is None`)
  recall is **fully skipped today** — guests get an empty `MemoryContext` every turn, no Redis
  lookup at all.
- Learn (`backend/app/memory/learn.py` + `backend/app/tasks/memory_learn.py`, P9-03/04): the
  post-turn Celery enqueue in `ChatService` only fires for a **logged-in** user
  (`_enqueue_learn`) — guests trigger nothing today.
- `backend/app/services/session_memory.py` (`SessionMemory`, Redis-backed in P1-05) — the
  existing per-session **conversation transcript** store; a good structural model (`load`/
  `append`, TTL-refreshed) for a new, small, Redis-backed **guest personalization** store, but
  it stores `ChatMessage`s — do not overload it; add a sibling store for personalization state
  instead (e.g. `backend/app/services/guest_memory.py`, an ABC + `RedisGuestMemory` impl next to
  `session_memory.py`'s pattern, or extend the existing Redis repository module used by
  `SessionMemory`/`SessionStore` if that's a cleaner fit — your call, but keep write access to
  Redis behind one seam like every other Redis-backed store in this repo).
- `backend/app/config.py` — `SESSION_MEMORY_TTL_SECONDS` / `GUEST_SESSION_TTL_SECONDS` are the
  existing guest-session lifetime knobs; reuse one of them (or a new
  `GUEST_MEMORY_TTL_SECONDS` mirroring the same default) rather than inventing an unrelated
  lifetime — guest personalization must not outlive the guest session itself.
- `backend/app/services/guest_upgrade.py::GuestUpgradeService.upgrade` — the existing
  guest→account promotion (P3-03), which already backfills the Redis conversation transcript
  into Postgres on upgrade (`_pair_turns` + `ConversationStore.persist_turn`). This is where the
  Redis-held personalization gets **migrated** to durable storage — mirror the same "read
  Redis, write Postgres, then let Redis expire naturally" pattern already used there for the
  transcript.
- `backend/app/memory/store.py::UserMemoryStore.add_memory` / the `Preference` write path added
  in P9-05 — reuse these for the durable write on upgrade; do not hand-roll a second insert path.
- `backend/app/memory/gdpr_filter.py` / `redact_contact_details` (P9-04) — **the same gates
  apply on the upgrade migration path**: a guest's ephemeral Redis memory must still pass
  through PII redaction + the Art. 9 exclusion filter before it becomes durable on upgrade (a
  guest could have accumulated a special-category or PII-bearing ephemeral memory during the
  session — do not durably persist it unfiltered just because "it was already in Redis").

## Acceptance criteria
- [ ] A small Redis-backed guest-personalization store (explicit-preference-like settings +
      a bounded list of learned-memory strings) keyed by `session_id`, TTL matching the guest
      session lifetime.
- [ ] Recall (P9-02's `memory_agent.recall`) is extended so a **guest** turn reads this Redis
      store (instead of unconditionally returning empty `MemoryContext`) — same shape
      (`preferences` + `memories`) the responder (P9-06) already knows how to use, so no
      responder change is needed.
- [ ] A learn-equivalent step for guests: post-turn, extract/update the guest's Redis-held
      personalization (can reuse the P9-03 extraction logic in-process — Celery is not required
      for an ephemeral Redis write, but is acceptable if it's a clean fit; your call, document
      it). PII redaction + GDPR Art. 9 exclusion (P9-04) still apply even to the *ephemeral*
      write — a career coach may hear Art.-9-adjacent things "usable within the turn only", but
      should not accumulate them into a running Redis memory list either, so keep the same gate
      wired here.
- [ ] Guest personalization **never** touches Postgres `preferences`/`user_memories` directly —
      only Redis, until upgrade.
- [ ] `GuestUpgradeService.upgrade` (or a step it calls) migrates the guest's Redis
      personalization into Postgres on successful upgrade: preferences → the user's
      `preferences` row; memories → `UserMemoryStore.add_memory` (through the same PII/GDPR
      gates as the logged-in learn path — reuse the P9-04 gate function, don't reimplement it).
      Best-effort: a migration failure must not break the upgrade flow itself (mirrors the
      existing transcript-backfill's fail-soft posture — check how that's handled today).
- [ ] Unit tests: guest recall returns Redis-held personalization; guest learn writes to Redis
      only (no Postgres call); TTL expiry means an old guest session's personalization is gone;
      upgrade migrates preferences + memories into Postgres and applies the PII/GDPR gate on the
      way in (a special-category ephemeral memory does not survive migration); upgrade with no
      guest personalization present is a clean no-op.

## Design references
- dev-board/app-design-and-features.md: §5.4 "Guests: personalization is session-only (Redis,
  ephemeral) — nothing durable is learned without an account; upgrading persists it."
- `backend/app/services/guest_upgrade.py` (P3-03 — the upgrade flow this extends).
- `backend/app/agents/memory_agent.py`, `backend/app/memory/learn.py`, `backend/app/memory/gdpr_filter.py`
  (P9-02/03/04 — the logged-in-path counterparts this mirrors and reuses).

## Constraints / non-goals
- No new frontend work.
- No change to the logged-in recall/learn/CRUD paths beyond what's needed to share the
  extraction/gate logic with the guest path (prefer extracting a shared helper over duplicating
  the extraction/gate code).
- No retention-purge job — that is P9-08 (guest data already dies with the Redis TTL, no purge
  job needed for guests specifically).
