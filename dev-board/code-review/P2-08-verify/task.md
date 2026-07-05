# Task P2-08-verify — P2 exit: restart-intact history + weighted vector/hybrid search
- **Phase:** P2   **Status:** ENG   **Tags:** (T)

## Scope
This is the **P2 exit-verification** item (dev-board/tasks.md, P2 section, final `(T)` line):

> Restart app → account chat history intact. Insert + cosine similarity query on a vector column returns
> expected neighbor - add extra weighting.

P2's stated exit criterion (plan.md) is: *"chat history survives restart for accounts; vector insert +
similarity query verified."* The individual building blocks already exist and are unit/integration tested
in isolation (P2-04 schema, P2-06 embeddings/hybrid search, P2-07 persistence/rehydration). This task is the
**phase-level integration proof** that ties them together end-to-end and demonstrates the **weighting**
behavior explicitly (the "add extra weighting" clause added to this line), not a redesign of any of them.

This is a **verification task**: build/extend integration tests (and, if useful, a small standalone
verification script) that *prove* the two halves below against **live Postgres** (and live Redis for the
restart half) — do not just re-assert unit-level behavior that already exists.

### Half 1 — Restart → account chat history intact
Building on P2-07 (`ConversationStore`, `_load_prior` Redis-reseeding fix, the two-turn regression test in
`test_chat_persistence.py`):
- Add (or extend) an integration test that runs a **multi-turn** logged-in conversation through `ChatService`
  end-to-end (stub `LLMClient`, live Postgres), simulates a full restart (fresh `SessionMemory` instance —
  Redis key loss), and proves a subsequent turn's model-visible context contains the pre-restart history —
  this already exists per P2-07's `test_restart_preserves_context_across_multiple_turns`; if it fully
  satisfies this half, cite it directly rather than duplicating it. If there's a gap (e.g. it doesn't restart
  *both* Redis and re-exercise the full `POST /api/chat` router path, only the service layer), close it here.
- Confirm guest sessions are unaffected by a restart in the same way they always were (no persisted history
  to lose — Redis TTL/loss simply means guest context resets, which is correct/expected, not a regression).

### Half 2 — Vector insert + cosine similarity + weighting
Building on P2-04 (`kb_chunks`/`user_memories` `vector(4096)` columns + binary-quantized HNSW ANN index) and
P2-06 (`EmbeddingClient`, pgvector write helper, `hybrid_search(query, *, k, vector_weight, text_weight, ...)`):
- A live-Postgres integration test that: inserts a handful of `kb_chunks` (or `user_memories`) rows with
  known embeddings (via the injectable fake-encoder seam from P2-06 — no real 8B-param model needed) chosen
  so the expected nearest neighbor is unambiguous by construction (e.g. one far outlier + one near-duplicate
  of the query vector), runs a pure cosine similarity query (`ORDER BY embedding <=> :q`), and asserts the
  expected row comes back first — this is the literal "insert + cosine similarity query on a vector column
  returns expected neighbor" acceptance bar.
- **Weighting proof** ("add extra weighting"): using `hybrid_search`, construct a fixture where one candidate
  row wins on vector similarity and a *different* candidate wins on full-text rank (`ts_rank` against
  `content_tsv`). Run `hybrid_search` with at least three weight configurations (e.g.
  `vector_weight=1.0/text_weight=0.0`, `vector_weight=0.0/text_weight=1.0`, and a middle blend) and assert the
  **top result changes** depending on the weights — proving the weighting parameter is not a no-op and
  measurably changes ranking. Document the exact fixture (which row should win under which weighting and why)
  in the test/engineer report so the proof is legible, not just "assert True".

## Acceptance criteria
- [ ] A live-Postgres, multi-turn restart integration test demonstrates account chat history is intact after
      a simulated restart (reuse/cite P2-07's test if it already satisfies this; extend only if there's a real
      gap — document which).
- [ ] A live-Postgres test inserts vectors and proves a pure cosine similarity query returns the expected
      (constructed) nearest neighbor.
- [ ] A live-Postgres test proves `hybrid_search`'s weight parameters measurably change the top-ranked result
      across at least 3 weight configurations, with the fixture's expected winners documented.
- [ ] `ruff` + `mypy` clean; full existing test suite still green (no regressions).
- [ ] Engineer report explicitly states the P2 exit criterion is met and cites the exact tests that prove it.

## Design references
- dev-board/plan.md — P2 exit criterion.
- dev-board/tasks.md — the P2 `(T)` exit-verify line this task implements (including the externally-added
  "add extra weighting" clause).
- dev-board/code-review/P2-04-migration-knowledge/engineer.md — vector column/index design.
- dev-board/code-review/P2-06-embeddings/engineer.md — `EmbeddingClient`, fake-encoder test seam,
  `hybrid_search` signature and weight semantics.
- dev-board/code-review/P2-07-persist-conversations/engineer.md — `ConversationStore`, restart-rehydration
  fix, existing two-turn regression test.

## Constraints / non-goals
- No new product features, endpoints, or schema changes — this task only adds/extends verification (tests,
  optionally a small standalone script) proving already-built P2 functionality end-to-end.
- Do not attempt to load the real `Qwen/Qwen3-Embedding-8B` model — continue using the injectable
  fake-encoder seam (`sentence-transformers`/`torch` are excluded from CI per existing convention).
- If a gap is found in an existing task's implementation while writing this verification (not just a missing
  test), flag it explicitly in the engineer report rather than silently patching unrelated modules — small,
  clearly-scoped fixes strictly required to make the proof pass are fine and should be called out.
