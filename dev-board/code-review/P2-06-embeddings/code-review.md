# Code review — P2-06-embeddings · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | app/repositories/vector_search.py:237-265 | `hybrid_search` (the embed-then-search convenience) has no direct test — only its two composed halves (`embed_query`, `hybrid_search_chunks`) are covered. It's a thin wrapper, but the injected-embedder duck-typing path is unexercised. | Optional: add a small test wiring a fake `EmbeddingClient` into `hybrid_search` to lock the composition. Defer if you judge the two-part coverage sufficient. |
| C2 | nit | app/llm/embeddings.py:159-163 | `embed_query` does not short-circuit empty/blank text (unlike `embed_documents([])`), so an empty query triggers a real model load + encode. Edge case, caller error rather than a crash. | Optional: document that `embed_query` assumes non-empty input, or short-circuit. Not blocking. |
| C3 | nit | app/repositories/vector_search.py:184-195 | Exact-cosine full-scan ranking (no ANN prefilter) is O(n) over the candidate set. Correct at current scale and explicitly documented as a deferred optimization tied to the P2-04 bit-Hamming HNSW index. | None required — noted for the architect's scale review; consistent with the P2-04 flag. |

## Notes
Verified locally (env loaded, live docker-compose Postgres on :5432):
- `ruff check` + `ruff format --check` clean; `mypy` strict clean (44 source files).
- `pytest tests/test_embeddings.py tests/test_vector_search.py` → **15 passed, 0 skipped** (integration tests genuinely ran against the live DB, not skipped).
- Import safety confirmed independently: after `SentenceTransformerEmbeddingClient()`, both `sentence_transformers` and `torch` are absent from `sys.modules` — the lazy-load + `encoder_factory` seam holds; no 8B model is fetched at import/construction.

Correctness / security spot-checks that passed:
- **Lazy-load seam** — double-checked locking on `asyncio.Lock` with the `is None` guard inside and outside the lock; factory invoked exactly once (asserted by `CountingFactory`), off the event loop via `asyncio.to_thread`. Sound.
- **Qwen3 query/doc split** — instruction prefix applied to queries only; `normalize_embeddings=True` matches the cosine metric used downstream. Output coercion handles both numpy `.tolist()` and nested-sequence encoders.
- **RRF weighting is genuinely caller-configurable and scale-invariant** — window `rank()` per signal, fused as `w_v/(k+rank_v) + w_t/(k+rank_t)`. The integration test proves the top result flips between the lexical-match and vector-match chunk purely by swapping weights (`vw=0/tw=1` → lexical first; `vw=1/tw=0` → semantic first), which is the actual weighting proof the task demanded, not just "a query runs". Choosing RRF over a raw weighted sum of incomparable-scale signals (cosine ~[0,1] vs unbounded `ts_rank`) is well-reasoned and documented.
- **SQL injection** — `query_text` reaches Postgres only via `func.plainto_tsquery('english', query_text)` (bound param); `kb_document_ids` via `.in_(list(...))` (bound params); embeddings via pgvector param binding. No string interpolation into SQL.
- **Layering (§8)** — embedding interface in `llm/`, all DB access confined to `repositories/vector_search.py`; `hybrid_search` injects the `EmbeddingClient` typed under `TYPE_CHECKING` only, so the repo has no runtime import of the LLM layer (no cycle). Write helpers `flush` but never `commit`, matching `get_db_session`'s caller-owns-transaction contract. Uses the P2-04 ORM models unchanged (no duplicate definitions).
- **User-scoping** — `search_user_memories` filters by `user_id`; cross-user isolation is explicitly tested (returns `[]` for another user's memory).

All acceptance criteria are met and verifiable. Findings are minor/nit only — none gate the task. The RRF vs weighted-sum choice is flagged for the system-architect as the one design judgment worth a second look, but it is a correct and defensible implementation.
