# Architecture review — P9-10-verify · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Phase-exit proof (plan.md P9) | Prove the whole chain: 2-session adaptation, 👎 changes behavior, inspect+delete — not per-task pieces re-run | `test_p9_exit_verification.py` drives real `run_learn_from_turn` (write) → compiled `stream_graph` recall (read) → `/api/memory` CRUD (delete) over the **same** `user_memories`/`preferences` rows; 8 tests, one per task point | none |
| A2 | §8 target structure | Memory code in `memory/`, persistence in `repositories/`, orchestration in `agents/`, CRUD in `api/`+`services/`, purge in `tasks/` | learn/gdpr_filter/store/guest_personalization in `memory/`; `list_user_memories` in `repositories/vector_search.py`; `MemoryService` in `services/`; `retention_purge` in `tasks/`; router in `api/memory.py` | none |
| A3 | Layering (Router→Service→Repo) | Panel reads/deletes the same rows learn wrote; no parallel data path | `wire_memory_api` composes the real `PostgresPreferenceStore` + `UserMemoryStore` over the same `provider`; point 3 asserts delete is gone from both `GET` and `recall` | none |
| A4 | §5.4 teachable memory loop | LangMem-style in-process store over pgvector `user_memories`; recall feeds responder | `UserMemoryStore(BaseStore)` over pgvector; point 1 asserts `final.memory.memories` carries the learned fact and the responder's assembled system prompt reflects it (P9-06) — discharges the open follow-up from [[ruling-responder-p4-06-scope]] | none |
| A5 | §5.5 feedback loop | A 👎 demotes/removes attributed memory; idempotent (P9-03 fix holds) | point 2: down-vote drives confidence to floor → `result.removed == [memory_id]`; subsequent recall drops it and surfaces the learned "avoid X" | none |
| A6 | GDPR gate (§4/§5.4) | PII redacted, Art. 9 dropped, on the real learn path **and** the guest-upgrade migration path | point 4 confirms via `GET /api/memory` (email redacted, diabetes dropped, benign kept); point 5 confirms Art. 9 dropped on migration (defense-in-depth) | none |
| A7 | Single-home primitives (DRY / point 8) | PII gate, list-memories query, dedup/confidence live once and are reused | point 8 asserts `special_category_of`→gdpr_filter, `gate_candidate`/`_near_duplicate`/`_clamp_confidence`→learn, `list_user_memories`→vector_search; guest paths **import** the gate, not re-implement — consistent with prior rulings | none |
| A8 | Guest posture (§4) | Guests Redis-only until upgrade | point 5 uses `InMemoryGuestMemory` (Redis seam) → migrator persists only on upgrade | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — verified against the tree
- [x] Honors locked decisions — Postgres(pgvector `vector(4096)`)+Redis only; in-process embeddings (real `EmbeddingClient` seam faked at the 8B edge, `EMBEDDING_DIM` const); LangGraph compiled graph exercised via `stream_graph`; no ReAct parser touched
- [x] Interfaces-before-implementations — test fakes the true external edges only (`EmbeddingClient`, `MemoryExtractor`, `UserEraser`, router) and runs every internal seam real
- [x] Budget posture respected — no paid/live-HF dependency; live Postgres via docker-compose, skips cleanly when unreachable

## Notes
- **Live-Postgres posture (vs P8-06 fully-offline).** Justified design choice, not a deviation: the P9 exit claim is that write/read/delete address the *same durable rows*; proving that over fakes would prove a shared dict, not a shared table. Matches the `*_persistence` precedent and skips cleanly without a DB. Approved.
- **Verification-only** — no product code changed, so no layering/interface regression is possible. The suite retires the P9 responder-personalization follow-up I had flagged in [[ruling-responder-p4-06-scope]]: state.memory now demonstrably reaches the responder's assembled messages.
- **Disclosed formatting drift (engineer flag).** The engineer ran `ruff format .` over 17 uncommitted sibling P9 files (whitespace/wrapping only, no logic). From a design-conformance view this is a no-op; it touches other tasks' *uncommitted* work rather than committed code, and was disclosed. Not a gate concern — the code-reviewer owns whether the cross-file formatting touch is acceptable process-wise.
- **P9 exit criterion: MET** on the design axis — cross-session adaptation, 👎-driven behavior change, and user inspect/delete are all proven over shared durable stores with the GDPR gate holding on every write path.
