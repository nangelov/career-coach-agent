# Engineer report — P2-06-embeddings · Revision 1

## Summary
Delivered the in-process **embedding client** and the **pgvector write + hybrid-search**
primitives on top of P2-04's `kb_chunks`/`user_memories` schema.

- `app/llm/embeddings.py` — `EmbeddingClient` ABC (ports-and-adapters, mirroring
  `LLMClient`) with `DIMENSION = 4096`, `embed_documents`, `embed_query`; plus
  `SentenceTransformerEmbeddingClient` wrapping `sentence_transformers.SentenceTransformer`
  (`settings.EMBEDDING_MODEL` = `Qwen/Qwen3-Embedding-8B`). Model load is **lazy** (built on
  first `embed_*` call, never at import/construction) and the encode backend is an
  **injectable seam** (`encoder_factory`) so tests use a deterministic fake and the real 8B
  model is never downloaded/run in CI or this sandbox.
- `app/repositories/vector_search.py` — write helpers (`add_kb_chunk`, `add_user_memory`)
  and search helpers (`hybrid_search_chunks` + the embed-then-search `hybrid_search`, and the
  vector-only `search_user_memories`). Hybrid search blends cosine similarity + lexical
  `ts_rank` with **caller-configurable weights** via Reciprocal Rank Fusion.

Verified: `ruff` + `ruff format` clean, `mypy --strict` clean (44 files), full backend suite
**123 passed** (15 new) against the live docker-compose Postgres; import/construction pulls
no ML stack.

## Files changed
- `backend/app/llm/embeddings.py` — **new.** `EmbeddingClient` interface (`DIMENSION=4096`,
  `embed_documents`/`embed_query`) + lazy, seam-injectable `SentenceTransformerEmbeddingClient`.
- `backend/app/repositories/vector_search.py` — **new.** `SearchResult`/`MemorySearchResult`
  dataclasses; `add_kb_chunk`, `add_user_memory`; `hybrid_search_chunks`, `hybrid_search`,
  `search_user_memories`.
- `backend/app/llm/__init__.py` — export `EmbeddingClient`,
  `SentenceTransformerEmbeddingClient`, `DEFAULT_QUERY_TASK`.
- `backend/app/repositories/__init__.py` — export the write/search helpers + result types.
- `backend/tests/test_embeddings.py` — **new.** Unit tests for the interface + seam (fake
  encoder): DIMENSION lock, lazy/once-only load, empty-batch short-circuit, query
  instruction-prefix applied to queries only, numpy-`.tolist()` coercion.
- `backend/tests/test_vector_search.py` — **new.** Real-Postgres integration tests: write
  helpers persist; **weight change flips ranking** (lexical-match vs vector-match chunk);
  limit + document filter; vector-only memory search + user scoping.

## Key decisions
- **Interface mirrors `LLMClient` (P1-01).** `EmbeddingClient` is a thin ABC with the fixed
  `DIMENSION=4096` (§6 item 3) and a **query/document split** rather than a single `embed`:
  Qwen3 retrieval wants queries wrapped `Instruct: {task}\nQuery:{text}` and documents left
  bare (confirmed against the `Qwen/Qwen3-Embedding-8B` model card — omitting the query
  instruction costs ~1-5% retrieval quality). `embed_documents` is the batched
  `embed(texts) -> list[list[float]]` shape the task asked for. The task description is a
  constructor arg (`query_task`, default = the model card's generic-retrieval instruction)
  so a corpus-specific wording can be tuned without a code change — the format is confirmed;
  the exact task string is worth revisiting against the career KB before production tuning,
  but is not a blocker.
- **Lazy load + injectable encode seam** (task's critical constraint). `SentenceTransformer`
  is imported and constructed only inside `_build_default_encoder`, invoked on first embed
  via `asyncio.to_thread` (kept off the event loop, built once under a lock). Tests inject
  `encoder_factory` returning a fake `.encode(...)` — so importing the module and
  constructing the client trigger **no** download (asserted in the verification run:
  `sentence_transformers`/`torch` absent from `sys.modules` after construction). Same posture
  as `HFOpenAICompatibleClient` not connecting at construction, and prior tasks' "no live
  model/token" caveats.
- **RRF blending over a raw weighted sum** (documented, per the "document whichever blending
  strategy you pick and why" ask). Cosine similarity (~[0,1]) and `ts_rank`
  (unbounded-small, corpus-dependent) live on incomparable scales, so `w_v*cos + w_t*ts_rank`
  would let the larger-magnitude signal dominate regardless of the weights. Reciprocal Rank
  Fusion fuses the two **rankings** instead — `score = w_v/(rrf_k+rank_vec) +
  w_t/(rrf_k+rank_text)` (`rrf_k=60`, the RRF-paper default) — which is scale-invariant, so
  the weights control each signal's influence directly and predictably. The integration test
  proves this: the same query flips its top result between the lexical-match and vector-match
  chunk purely by swapping the weights. Raw `vector_similarity` + `text_rank` are still
  returned per result for transparency/telemetry.
- **DB access stays in `repositories/` (§8).** New module
  `app/repositories/vector_search.py`; it uses the P2-04 ORM models unchanged (no duplicated
  definitions). Write helpers `flush` (PK populated) but never `commit` — the caller owns the
  transaction boundary, matching `get_db_session`'s contract.
- **`user_memories` search is vector-only, by design.** P2-04 gave that table no
  `tsvector`/GIN column (LangMem recalls memories by semantic proximity to the turn, not
  lexically), so there's no lexical signal to blend — documented in `search_user_memories`
  and the module docstring, exactly as the task allowed.
- **`hybrid_search` composition keeps layering clean.** The `query: str` → `embed_query` →
  search convenience takes the `EmbeddingClient` as an **injected** parameter, typed under
  `TYPE_CHECKING` only (duck-typed at runtime), so the repository has no hard import
  dependency on the LLM layer and no import cycle; the concrete client is wired by the future
  RAG service (P4/P5).
- **Exact-cosine ranking now; bit-Hamming ANN prefilter deferred.** `hybrid_search_chunks`
  ranks over the (optionally doc-filtered) candidate set with exact cosine on the
  full-precision `vector(4096)` column — correct at any size, right for current data. The
  P2-04 `binary_quantize(...)::bit(4096) bit_hamming_ops` HNSW index is the intended top-N
  prefilter at scale (same result contract); deferred as an optimization, documented in the
  module docstring. Flagging for the architect: this is consistent with the P2-04 flag that
  4096 dims exceed pgvector's ANN cap.

## How to verify
From `backend/` (venv has ruff/mypy/pytest + sqlalchemy/pgvector/asyncpg; the live db
container is up):
```bash
# lint + strict types
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy app/ migrations/                      # Success: no issues found in 44 source files

# unit tests need no DB; integration tests need the live Postgres
set -a && . ../.env && set +a
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}"
.venv/bin/pytest tests/test_embeddings.py tests/test_vector_search.py -q   # 15 passed
.venv/bin/pytest -q                                                        # 123 passed
```
**Actually run here** (live pgvector Postgres on :5432): 15 new tests pass; full suite
**123 passed**. Import safety asserted — after `SentenceTransformerEmbeddingClient()`,
`sentence_transformers` and `torch` are absent from `sys.modules`. `ruff`/`ruff format` clean;
`mypy --strict` clean. The weighting test asserts the top result flips between the
lexical-match and vector-match chunk when `text_weight`/`vector_weight` are swapped — the
actual proof the weights blend, not just that a query runs.

## Self-check
- [x] Meets acceptance criteria — `EmbeddingClient` interface + `SentenceTransformerEmbeddingClient`
  with lazy load (no download at import/construction); documented injectable fake-encoder
  seam; pgvector write helpers use the P2-04 ORM models (no parallel definitions);
  `hybrid_search` blends cosine + `ts_rank` with caller-configurable weights, proven against
  live Postgres to change ranking; ruff + mypy clean.
- [x] No secrets committed; Router→Service→Agent/Repo layering respected — embedding
  interface in `llm/`, DB access confined to `repositories/vector_search.py`, no service/router
  touched; `hybrid_search` injects the `EmbeddingClient` (no repo→llm runtime import).
- [x] Tests/lints pass (pasted above): 123 passed, ruff clean, mypy --strict clean.
- [x] Real 8B model never downloaded/run in CI or sandbox — the encode seam + lazy load are
  the sole path; import safety verified.

## Notes for reviewers
- The one strategy choice worth a look is **RRF vs weighted-sum blending** (rationale above).
  It directly serves the next P2 exit task ("add extra weighting") — that task can add more
  ranked signals (e.g. recency, source-type boosts) as additional RRF terms without changing
  the result contract.
- `sentence-transformers`/`torch` remain out of the CI curated install; `test_embeddings.py`
  needs neither (fake encoder), and `test_vector_search.py` auto-skips without a reachable
  Postgres — both stay CI-green on the free tier. `sentence_transformers` is untyped under
  mypy's `ignore_missing_imports` (same posture as `langgraph`/`docling`); first-party code
  around it is fully typed.
