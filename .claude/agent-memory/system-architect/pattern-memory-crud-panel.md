---
name: pattern-memory-crud-panel
description: P9-05 blessed — /api/memory transparency panel (view/edit prefs + view/delete learned memories), opt-out no-confirmation surface
metadata:
  type: project
---

P9-05 memory-CRUD API (§5.4 / §6.10 silent-but-viewable/deletable, opt-out) — APPROVED rev 1.

**Blessed shape (reuse for P9-07/09 and any future personalization CRUD):**
- Router `api/memory.py` → `MemoryService` → two seams: `PreferenceStore` (ABC in `services/preferences.py`
  + `InMemory` double; Postgres adapter `repositories/preference_store.py`, `ON CONFLICT (user_id)` upsert —
  exact `ProfileStore` precedent) and `LearnedMemoryStore` Protocol satisfied by `UserMemoryStore`
  (DIP seam, mirrors RAG `SessionProvider`).
- Preferences = identity JSONB (one row/user), NOT a pgvector primitive — right store per §4.
- Endpoints: split `GET` / `PUT /api/memory/preferences` / `DELETE /{id}` / bulk `DELETE` accepted over the
  §9 `GET/PUT/DELETE /api/memory` single-path (task permitted "your call").
- Ownership: owner = token subject only; not-owned/unknown id → uniform 404 (extended `delete_user_memory`
  with optional `user_id` — no parallel primitive; learn step's unscoped call untouched). Guest → 403 (durable-only).
- Embeddings never cross the wire (`UserMemoryListItem`/`LearnedMemory` display columns only, §7.6).
- No per-fact confirmation workflow — immediate (contrast P8-03 `source='ai'` propose/approve). §6.10.
- Explicit prefs override inferred memories (§5.4 pt4) confirmed in `memory_agent.recall` (P9-02), not re-implemented.

**Why:** keeps the panel a thin CRUD surface consistent with [[pattern-memory-recall-store]] / [[pattern-memory-learn-step]]
(single home = `UserMemoryStore`, extend-not-duplicate).

**How to apply:** for P9-09 frontend, note `PUT /preferences` is a FULL-document replace (partial body clears
unspecified fields) — submit the whole form, not a delta. For P9-07 guest personalization, keep it Redis-only
(this durable panel stays account-gated).
