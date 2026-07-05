---
name: project-hybrid-search
description: Blessed P2-06 embedding + hybrid-search conventions (RRF blend, injectable encoder seam, vector-only user_memories) for P2-exit/P4/P5 consistency
metadata:
  type: project
---

P2-06 (`llm/embeddings.py` + `repositories/vector_search.py`) established the embed+search primitive. Blessed conventions to keep consistent:

- **Hybrid search = RRF, not raw weighted sum.** `hybrid_search_chunks` blends cosine + `ts_rank` via Reciprocal Rank Fusion (`score = w_v/(rrf_k+rank_v) + w_t/(rrf_k+rank_t)`, `rrf_k=60`). Chosen because cosine (~[0,1]) and `ts_rank` (unbounded-small) are incomparable scales; RRF is scale-invariant so weights control influence directly. Weights are **caller-configurable params** (defaults 0.5/0.5). The task explicitly permitted RRF as a documented alternative.
- **How to apply:** the next P2 exit task ("add extra weighting") should add signals (recency, source-type boosts) as **additional RRF terms**, not a different blending scheme — same result contract.
- **`user_memories` is vector-only by design** (no tsvector/GIN column in P2-04; LangMem recalls semantically). Do not require hybrid there.
- **Layering:** DB access stays in `repositories/vector_search.py`; the `EmbeddingClient` is **injected** into `hybrid_search` and imported only under `TYPE_CHECKING` (no repo→llm runtime cycle). Concrete client wired by the RAG service in P4/P5.
- **Embedding seam:** `EmbeddingClient` ABC mirrors [[project-llm-layer-seam]]'s `LLMClient`; real ST model is lazy-loaded + behind an injectable `encoder_factory` (real 8B never runs in CI/sandbox). Dim locked at 4096 per [[project-v2-locked-stack]] #3.
- **Deferred (accepted):** exact cosine scan now; binary-quantize HNSW prefilter is the at-scale optimization (same contract). Query-instruction task string tunable pre-production.
