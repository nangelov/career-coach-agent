# Engineer report — P2-08-verify · Revision 1

## Summary
Delivered the **P2 phase-level exit-verification** proof as a single, citable integration
module — `backend/tests/test_p2_exit_verification.py` — that ties the already-built P2 building
blocks (P2-04 schema, P2-06 embeddings/hybrid search, P2-07 persistence/rehydration) together
**end-to-end against live Postgres** and demonstrates the **weighting** behaviour explicitly.
This is a verification-only task: **no product code, schema, or endpoints changed** — one new
test file (5 tests), all of which actually run (not skip) against the live docker-compose
Postgres and pass.

**The P2 exit criterion is met**, proven by the tests cited below (plan.md P2: *"chat history
survives restart for accounts; vector insert + similarity query verified"* + the tasks.md
`(T)` clause *"add extra weighting"*).

## Files changed
- `backend/tests/test_p2_exit_verification.py` — **new.** 5 live-Postgres integration tests
  across the two exit halves (restart-intact account history; vector insert + pure cosine +
  weighting sweep). Self-contained (own skip-fixtures + scripted LLM fakes), matching the
  existing per-file integration-test idiom (`test_vector_search.py` / `test_conversation_store.py`
  each carry their own `_postgres_reachable` + fixtures).

No other files touched — no gaps requiring a production fix were found (see *Gaps* below).

## Key decisions
- **Half 1 gap closed (live DB + full router path).** P2-07's
  `test_restart_preserves_context_across_multiple_turns` proves multi-turn restart survival at
  the **service layer with a fake in-memory store**. The two real gaps per the task were (a) it
  never hits **live Postgres**, and (b) it never re-exercises the **`POST /api/chat` router
  path**. Closed with two tests:
  - `test_restart_preserves_account_history_multi_turn_live_postgres` — drives 2 pre-restart +
    2 post-restart logged-in turns through the **real `ChatService` + real
    `PostgresConversationStore`** (scripted LLM stub, no HF/token). Asserts turn 3 rehydrates
    the pre-restart pairs from Postgres **and** turn 4 still sees turn 1 (proving both the
    Postgres rehydration *and* the fresh-working-memory re-seed against a live DB — the live
    analogue of P2-07's C1 regression).
  - `test_restart_preserves_account_history_via_router_path_live_postgres` — the same restart
    proof end-to-end through `POST /api/chat`: the SSE body is fully drained (so the
    post-`done` durable persist runs), the service is swapped for a fresh one (restart), and a
    second request for the same session+user rehydrates turn 1 from Postgres.
  A "restart" is modelled by a **fresh `InMemorySessionMemory`** (working-memory/Redis key
  loss) on a rebuilt service over the **same** durable store — the exact condition that forces
  the Postgres fallback in `ChatService._load_prior`.
- **Guest-restart confirmed unaffected.** `test_guest_restart_has_no_history_live_postgres`
  proves a guest turn (no `user_id`) persists nothing and, after a restart, rehydrates nothing
  — the correct/expected reset, not a regression (§4: *"Guests get NO persisted history"*).
- **Half 2 — pure cosine acceptance bar.**
  `test_pure_cosine_similarity_returns_expected_neighbor` inserts three chunks with constructed
  4096-dim embeddings — a **near-duplicate** of the query (dist ≈ 0.005), a 45° vector
  (dist ≈ 0.293), and an **orthogonal far outlier** (dist = 1.0) — and runs a **pure
  `ORDER BY embedding <=> :q`** cosine query (via `KbChunk.embedding.cosine_distance`, the `<=>`
  operator). Asserts the near-duplicate comes back first and the full ordering is
  near → mid → far. This is the literal "insert + cosine similarity query on a vector column
  returns expected neighbor" bar, distinct from the RRF hybrid path.
- **Half 2 — weighting is not a no-op (4-config sweep, documented winners).**
  `test_hybrid_search_weighting_changes_top_result_across_configs` builds two chunks whose
  signals disagree (a *lexical* "kubernetes" text match with an orthogonal embedding vs. a
  *semantic* chunk whose embedding equals the query vector) and sweeps four
  `(vector_weight, text_weight)` configs, asserting the documented winner of each:

  | config | (vector, text) | expected top | why |
  |--------|----------------|--------------|-----|
  | 1 | (1.0, 0.0) | semantic | pure vector → cosine-0 chunk |
  | 2 | (0.6, 0.4) | semantic | vector-leaning blend still favours vector |
  | 3 | (0.4, 0.6) | lexical  | text-leaning blend flips to the lexical hit |
  | 4 | (0.0, 1.0) | lexical  | pure lexical → the "kubernetes" text match |

  The top result **flips** at the crossover between config 2 and 3 — proving the weight
  parameter measurably changes ranking. A symmetric `0.5/0.5` blend is **intentionally
  avoided** and documented: with exactly two candidates whose ranks are mirror images, RRF ties
  them (RRF favours whichever item ranks 1 on a signal, so `1/61 + 1/63 == 1/63 + 1/61`), so the
  **asymmetric** 0.6/0.4 and 0.4/0.6 blends give the deterministic, assertable crossover. This
  is the legible "add extra weighting" proof, extending P2-06's 2-config
  `test_hybrid_search_weights_change_ranking`.
- **Self-contained file over shared `conftest.py`.** The skip-fixtures and scripted fakes are
  duplicated locally rather than extracted, matching the codebase's existing per-file
  integration-test convention (each live-DB suite carries its own) and keeping the "P2 exit
  proof" readable as one unit; refactoring existing suites into a shared conftest would be
  out-of-scope churn/regression risk.
- **DB left as found.** Commit-based Half-1 tests create a throwaway `users` row and delete it
  in fixture teardown (GDPR cascade removes every session/conversation/message created);
  read-only Half-2 tests run inside a rolled-back transaction — same posture as the existing
  integration suites.

## Gaps found
None requiring a production fix. The existing P2-04/06/07 implementations satisfied every proof
without modification; the only gap was **missing phase-level verification**, which this task
adds. P2-07's service-layer/fake-store restart test is cited and complemented (not duplicated)
by the live-DB + router-path tests here.

## How to verify
From `backend/`, with the live docker-compose Postgres up (db on :5432, schema at head `0004`):
```bash
set -a && . ../.env && set +a
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}"
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy app/ tests/test_p2_exit_verification.py
.venv/bin/pytest tests/test_p2_exit_verification.py -v   # 5 passed (not skipped)
.venv/bin/pytest -q                                      # full suite
```
Actually run here (live pgvector Postgres on :5432, `alembic current` = `0004 (head)`):
- `ruff check .` → **All checks passed!**; `ruff format --check .` → clean.
- `mypy app/ tests/test_p2_exit_verification.py` → **Success: no issues found in 42 source files**.
- `pytest tests/test_p2_exit_verification.py -v` → **5 passed** — all four live-DB tests + the
  cosine test ran against real Postgres (0 skipped).
- `pytest -q` → **141 passed** (was 136 before; +5 new), **no regressions**.

## P2 exit criterion — met, with the exact proving tests
- *"chat history survives restart for accounts"* →
  `test_restart_preserves_account_history_multi_turn_live_postgres` (service + live Postgres,
  multi-turn) and `test_restart_preserves_account_history_via_router_path_live_postgres`
  (`POST /api/chat` end-to-end + live Postgres); guests confirmed unaffected by
  `test_guest_restart_has_no_history_live_postgres`.
- *"vector insert + similarity query verified"* →
  `test_pure_cosine_similarity_returns_expected_neighbor` (insert + pure `<=>` cosine query
  returns the constructed nearest neighbour).
- *"add extra weighting"* → `test_hybrid_search_weighting_changes_top_result_across_configs`
  (four weight configs, top result flips at the documented crossover).

## Self-check
- [x] Meets acceptance criteria — live-Postgres multi-turn restart proof (service + router
  path); pure cosine `<=>` query returns the constructed neighbour; `hybrid_search` weights
  measurably change the top result across 4 configs with documented winners; ruff + mypy clean;
  full suite green (141 passed, no regressions); engineer report states the exit criterion is
  met and cites the exact tests.
- [x] No secrets committed; Router→Service→Agent/Repo layering respected — verification only,
  no production code touched; tests drive the real service/router/repository through their
  public seams (scripted LLM fake, injected fake embeddings).
- [x] Honors locked decisions — Postgres+Redis only; real 8B embedding model never loaded
  (constructed 4096-dim fake vectors); no ReAct/SSO scope crept in; free/OSS posture (tests
  skip cleanly without a DB so CI stays green).
- [x] Tests/lints pass (pasted above): 141 passed, ruff clean, mypy clean.
