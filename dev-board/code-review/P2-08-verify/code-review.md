# Code review — P2-08-verify · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/tests/test_p2_exit_verification.py:279-302 | `test_guest_restart_has_no_history_live_postgres` proves the *guest context resets* after a restart (fresh service sees no prior turns), but it does not assert that **nothing was written to Postgres** for that session. The "no durable rows" property is only inferred from a fresh in-memory store seeing nothing — which would also pass if persistence silently wrote rows under a guest path. The stronger DB-level "persists nothing" assertion already exists at unit level (P2-07), so this is legible enough as a phase proof, but a direct `messages`-count-for-session == 0 assertion would make the guest half self-contained. Optional. | Consider adding a query asserting no `messages`/`conversations` rows exist for `session_id` after the guest turn; or leave as-is and rely on the cited P2-07 unit coverage. |

## Notes
Verified by running, not just reading — live pgvector Postgres up (`career-coach-agent-db-1`, `alembic current` = `0004 (head)`):
- `ruff check` + `ruff format --check` on the new file: clean.
- `mypy tests/test_p2_exit_verification.py`: Success, no issues.
- `pytest tests/test_p2_exit_verification.py -v`: **5 passed, 0 skipped** — all ran against real Postgres.
- `pytest -q` (full suite): **141 passed**, no regressions (was 136; +5 new).

Genuineness of the proofs (the core ask) — all three halves are real, not tautological:

- **Half 1 (restart → account history intact).** The multi-turn test drives 2 pre-restart + 2 post-restart logged-in turns through the *real* `ChatService` + *real* `PostgresConversationStore` over live Postgres, with only the LLM/tool registry faked. A "restart" is modelled correctly as a fresh `InMemorySessionMemory` over the same durable store — the exact condition that forces the Postgres fallback in `ChatService._load_prior`. Crucially the test asserts turn **4** still sees turn 1 (`turn4` contains `Q1`/`A1`), which only holds if the rehydration **seeds the working memory back** (chat.py:352-353). This is precisely the P2-07 rev-1 defect class (cache-fallback that doesn't repopulate, missed by single-post-restart tests) — the test would fail if that seed-back regressed, so it is a real guard, not a restatement of the fake-store unit test. The router-path variant additionally drains the full SSE body (so the post-`done` durable persist runs) and re-drives `POST /api/chat` on a fresh service, closing the "service-layer only" gap the task called out.
- **Half 2a (pure cosine).** Fixture is unambiguous by construction: a near-duplicate (dist ≈ 0.005), a 45° vector (dist ≈ 0.293), and an orthogonal outlier (dist = 1.0), queried via the pgvector `<=>` operator (`KbChunk.embedding.cosine_distance`) with `ORDER BY ... asc`. Asserts both the winner and the full ordering. Verified the geometry independently (spikes at fixed indices → the claimed distances hold). This is the literal acceptance bar, distinct from the RRF hybrid path.
- **Half 2b (weighting not a no-op).** The two candidates have deliberately disagreeing signals (lexical "kubernetes" text match with orthogonal embedding vs. a semantic chunk whose embedding equals the query). The four-config sweep asserts the **top result flips** (semantic → lexical) between config 2 `(0.6,0.4)` and config 3 `(0.4,0.6)`. I re-derived the RRF scores by hand (rrf_k=60): semantic `w_v/61 + w_t/62`, lexical `w_v/62 + w_t/61` — the crossover is exact and deterministic, and the documented reason for **avoiding** the symmetric `0.5/0.5` blend (RRF ties mirror-image ranks) is correct. A no-op weight parameter would keep the winner constant and fail configs 3/4, so this is a genuine proof, not `assert True`. Extends P2-06's 2-config test rather than duplicating it.

No production code was changed (verification-only, as scoped); the existing P2-04/06/07 implementations satisfied every proof without modification. Layering respected (tests drive the real service/router/repository through public seams). Locked decisions honored: Postgres+Redis only, the real 8B embedding model is never loaded (constructed 4096-dim fake vectors via the P2-06 seam), tests skip cleanly without a DB so CI stays green. Engineer report explicitly states the P2 exit criterion is met and cites the exact proving tests.

C1 is a nit and does not gate.
