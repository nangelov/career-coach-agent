---
name: hybrid-search-rrf
description: kb_chunks hybrid search blends cosine + ts_rank via Reciprocal Rank Fusion with caller-configurable weights (P2-06)
metadata:
  type: project
---

`app/repositories/vector_search.py` (P2-06) is the pgvector write + search primitive over
the P2-04 `kb_chunks`/`user_memories` schema. Key established conventions to build on:

- **Blending = Reciprocal Rank Fusion (RRF), not a raw weighted sum.**
  `score = vector_weight/(rrf_k+rank_vec) + text_weight/(rrf_k+rank_text)` (`rrf_k=60`).
  **Why:** cosine similarity (~[0,1]) and `ts_rank` (unbounded-small) are on incomparable
  scales — a weighted sum lets the larger-magnitude signal dominate regardless of weights;
  RRF fuses rankings so weights control influence directly.
  **How to apply:** the next P2 exit task ("add extra weighting") should add signals (recency,
  source-type boost, etc.) as **additional RRF terms**, keeping the same `SearchResult`
  contract — do not switch to score blending.

- **Weights are caller params** (`vector_weight`/`text_weight`, default 0.5/0.5), not constants.
- **`user_memories` search is vector-only** — that table has no tsvector/GIN (LangMem recalls
  by semantic proximity), so there's no lexical signal to blend. Don't try to hybrid it.
- **Ranking is exact cosine** on the full `vector(4096)` column; the P2-04 bit-Hamming HNSW
  ANN prefilter (see [[pgvector-4096-index-limit]]) is deferred as a scale optimization, not
  wired yet — same result contract when added.
- **`EmbeddingClient`** (`app/llm/embeddings.py`): lazy-loads the ST model (never at
  import/construction), encode is behind an injectable `encoder_factory` seam so tests use a
  fake — never download/run the real `Qwen/Qwen3-Embedding-8B` in CI/sandbox. Query/document
  split: queries get `Instruct: {task}\nQuery:{text}`, documents get no prefix.
