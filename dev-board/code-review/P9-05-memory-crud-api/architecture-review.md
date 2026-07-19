# Architecture review — P9-05-memory-crud-api · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | code in sanctioned modules (api/services/schemas/repositories/memory) | `api/memory.py`, `services/memory.py`, `services/preferences.py`, `schemas/memory.py`, `repositories/preference_store.py`, `repositories/vector_search.py`, `memory/store.py` | none |
| A2 | Layering (Router→Service→Repository) | router HTTP-only; service policy; repo owns SQL; caller commits | router maps auth/status only; `MemoryService` owns validate/serialize + str→UUID boundary; SQL in `vector_search.py`/`preference_store.py`; store methods own their commit | none |
| A3 | Interfaces-before-impl | real seams, not concrete imports | `PreferenceStore` ABC + `InMemoryPreferenceStore` (mirrors `ProfileStore`); `LearnedMemoryStore` Protocol (mirrors RAG `SessionProvider` DIP seam) | none |
| A4 | §6.10 opt-out / no per-fact confirmation | immediate edits & deletes, no propose/approve | PUT/DELETE apply immediately; no queue/approval surface (contrast P8-03 `source='ai'` flow) | none |
| A5 | §5.4 preference fields | tone, formality, language, focus areas, do/don't (JSONB, user-editable) | `Preferences`: tone/formality/language/focus_areas/avoid, length-capped, one JSONB row/user | none |
| A6 | §5.4 pt 4 explicit overrides inferred | preferences authoritative, injected ahead of memories | confirmed in `memory_agent.recall` (P9-02), not re-implemented; this task edits the same row | none |
| A7 | §7.6 embeddings never cross the wire | vector stays in DB | `UserMemoryListItem`/`LearnedMemory` carry display columns only; no embedding field | none |
| A8 | §7 AuthZ / no-leak | owner = token subject; not-owned id → uniform 404 | `_require_user` (guest 403); ownership-scoped `delete_user_memory(user_id=…)` → False → 404; no path/body user_id | none |
| A9 | §4 / §5.4 data ownership | prefs JSONB one-per-user; user_memories user-scoped; guests durable-free | `ON CONFLICT (user_id)` upsert; user-scoped list/clear; guest rejected (no durable row) | none |
| A10 | Locked stack | Postgres+pgvector+JSONB + SSO-only; in-process embedder lazy | Postgres only; `require_auth`; embedder never model-loads on CRUD paths (lazy) | none |
| A11 | Budget posture (§11) | free/OSS/self-hosted | no paid services introduced | none |
| A12 | Phase fit (P9) | CRUD surface only; no guest personalization (P9-07) / frontend (P9-09) / recall-learn changes | scope held; recall/learn untouched beyond adding the list/clear/scoped-delete read primitives | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Repo)
- [x] Honors locked decisions (Postgres+Redis only; SSO-only auth; in-process embeddings, lazy here)
- [x] Interfaces-before-implementations (`PreferenceStore` ABC, `LearnedMemoryStore` Protocol)
- [x] Budget posture respected (free/OSS/self-hosted)

## Notes
- Endpoint shape: design (§9, table row `/api/memory`) lists `GET/PUT/DELETE /api/memory`; engineer split
  into `GET`, `PUT /api/memory/preferences`, `DELETE /{memory_id}`, and bulk `DELETE`. Task explicitly
  permitted this ("your call, document it") and it is documented — accepted. Route order is fine: the static
  `DELETE ""` and `DELETE /{memory_id}` do not collide.
- `PUT /api/memory/preferences` is a **full-document replace** (all `Preferences` fields optional with
  defaults, so a partial body silently clears unspecified fields). Correct PUT semantics and fine for the
  P9-09 panel (which submits the whole form), but flag for the frontend task: send the complete document,
  not a delta. Cheap-to-adjust-later, not a design blocker.
- DRY: `LearnedMemoryStore` Protocol restates a subset of `UserMemoryStore` — consistent with the blessed
  DIP-seam pattern (`SessionProvider`), not duplication to unwind. `delete_user_memory` extended with an
  optional `user_id` rather than a parallel primitive (learn step's unscoped call untouched) — good KISS/DRY.
- Preferences seam correctly modeled as identity (`PreferenceStore` + Postgres adapter, `ProfileStore`
  precedent) rather than a pgvector primitive — the right store for a JSONB-per-user document (§4).
