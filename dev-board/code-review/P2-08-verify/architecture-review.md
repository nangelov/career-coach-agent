# Architecture review — P2-08-verify · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure / scope | Verification-only: no new endpoints, schema, or product code — just phase-exit tests | Single new file `backend/tests/test_p2_exit_verification.py`; no production/migration/router files touched | None |
| A2 | Phase fit — P2 exit (plan.md P2) | Tie P2-04/06/07 together end-to-end; prove restart-intact history + vector insert/similarity + weighting | 5 live-Postgres tests map 1:1 onto the exit clauses; cites P2-07's service-layer test and closes its two real gaps (live DB + `POST /api/chat` router path) rather than duplicating it | None |
| A3 | Layering (Router→Service→Repo, §8) | Drive real seams; services never touch the driver; DB access stays in repo layer | Tests exercise real `ChatService` + `PostgresConversationStore` + FastAPI router via injected fakes (`_FakeRouter`/`_FakeRegistry`); vector half uses `hybrid_search_chunks` + ORM `<=>` — no new DB access invented | None |
| A4 | Cosine query on `vector(4096)` (§4, P2-04) | Insert + `ORDER BY embedding <=> :q` returns constructed neighbor; dim consistent with migrations | Uses `KbChunk.embedding.cosine_distance` (the `<=>` operator) over `EMBEDDING_DIM = 4096`; near→mid→far ordering asserted deterministically | None |
| A5 | Weighting proof (P2-06 hybrid_search, §4 "Hybrid Search with weights") | Weights measurably change top rank across ≥3 configs; fixture winners documented | 4-config sweep flips top result at the 0.6/0.4 → 0.4/0.6 crossover; faithful to the blessed RRF semantics (asymmetric blends chosen precisely because RRF ties mirror-image ranks at 0.5/0.5 — proves, not contradicts, the design) | None |
| A6 | Data ownership §4 (guests Redis-only, no persisted history) | Guest restart loses context by design, not regression | `test_guest_restart_has_no_history_live_postgres` asserts guest turn persists/rehydrates nothing | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — tests only; drives production seams through their public interfaces
- [x] Honors locked decisions — Postgres (pgvector + JSONB) + Redis only; **real 8B embedding model never loaded** (constructed 4096-dim fakes via the P2-06 injectable seam); no ReAct/SSO scope crept in; `dim=4096` consistent with migrations
- [x] Interfaces-before-implementations — reuses `ConversationStore` port, `EmbeddingClient` duck-type seam, `LLMRouter` seam via `_FakeRouter`; nothing re-declared
- [x] Budget posture respected (free/OSS/self-hosted) — skip-not-fail gating keeps DB-less CI green; no paid/managed tier introduced

## Notes
- Consistent with prior rulings: matches the blessed P2-06 hybrid-search design (caller-configurable RRF weights, vector-only `user_memories`) and the P2-07 conversation-persistence pattern (`ConversationStore` port + Postgres adapter, restart = fresh `InMemorySessionMemory` forcing Postgres rehydration). This task cites-and-complements rather than re-litigating those designs — the correct posture for a phase-exit verification.
- Self-contained skip-fixtures/fakes duplicated per-file (over a shared `conftest.py`) matches the existing integration-suite convention; refactoring the other live-DB suites into shared fixtures would be out-of-scope churn — agreed, not a design gap.
- Design ruling for future phase-exit `(T)` tasks: verification tasks should exercise already-built seams end-to-end and cite prior-task tests, closing only genuine gaps (here: live DB + router path) — no new product surface. This is the accepted pattern.
- No design deviations found; no follow-ups logged.
