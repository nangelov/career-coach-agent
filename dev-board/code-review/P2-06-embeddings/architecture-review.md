# Architecture review — P2-06-embeddings · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Embedding client in `llm/`; DB access in `repositories/` | `EmbeddingClient` + impl in `app/llm/embeddings.py`; all pgvector read/write in `app/repositories/vector_search.py` | none |
| A2 | Layering (Router→Service→Repo; services/repos don't leak across layers) | Repo must not depend on the LLM layer at runtime | `hybrid_search` takes `EmbeddingClient` as an **injected** param, imported only under `TYPE_CHECKING`, duck-typed at runtime — no repo→llm import cycle | none |
| A3 | Interfaces before implementations (§6.7 pattern; P1-01 `LLMClient` precedent) | ABC seam + swappable concrete adapter, mirroring `LLMClient` | `EmbeddingClient` ABC (`DIMENSION`, `embed_documents`, `embed_query`) + `SentenceTransformerEmbeddingClient` adapter | none |
| A4 | Locked decision #3 — embeddings | `Qwen/Qwen3-Embedding-8B` in-process via `sentence-transformers`, **dim 4096**, no API cost | `settings.EMBEDDING_MODEL` default `Qwen/Qwen3-Embedding-8B`; `DIMENSION = 4096` matches `EMBEDDING_DIM`/`vector(4096)` in P2-04 `kb_chunks`/`user_memories`; in-process ST | none |
| A5 | Budget posture (§11 free/OSS/self-hosted) | No paid/managed embedding API; runs in-process | Pure in-process ST; no external call; lazy model load means import/construction pulls no ML stack | none |
| A6 | Data ownership (§4) — user-scoped memory | `user_memories` queries scoped to one user | `search_user_memories` filters `WHERE user_id == :user_id` | none |
| A7 | Phase fit (P2) — no premature coupling | No LangMem (P9), no RAG agent/tool (P4/P5); deliver embed+search primitive only | Write + hybrid-search primitives only; LangMem/RAG explicitly deferred and documented | none |
| A8 | "Hybrid Search with weights" (§4 / tasks.md P2) | Blend cosine + `ts_rank` with **caller-configurable** weights | `hybrid_search_chunks` blends both via RRF with `vector_weight`/`text_weight` params (defaults 0.5/0.5); integration test proves weight swap flips ranking | none — RRF is a task-sanctioned, documented alternative to raw weighted sum |
| A9 | P2-04 schema reuse | Use P2-04 ORM models; do not re-declare | Uses `KbChunk`/`UserMemory` from `models.knowledge`; generated `content_tsv` maintained by Postgres, never written | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — LLM seam in `llm/`, driver access confined to `repositories/vector_search.py`, no repo→llm runtime import.
- [x] Honors locked decisions — in-process `sentence-transformers`, dim 4096 consistent with P2-04 migration; no ReAct/Postgres+Redis/SSO surface touched.
- [x] Interfaces-before-implementations — `EmbeddingClient` ABC mirrors `LLMClient`; encode backend behind an injectable `encoder_factory` seam.
- [x] Budget posture respected — free/OSS/self-hosted, no external embedding API, lazy load keeps CI ML-free.

## Notes
- **RRF vs raw weighted sum (blessed).** The task explicitly permitted "a documented alternative such as reciprocal-rank-fusion … document whichever blending strategy you pick and why." The engineer's scale-invariance rationale (cosine ~[0,1] vs unbounded-small `ts_rank`) is sound and is the standard dense+lexical fusion. Weights remain caller-configurable, which is the load-bearing design ask. Approved as the project's hybrid-search convention; the next P2 exit task ("add extra weighting") can add ranked signals (recency, source-type) as further RRF terms without changing the result contract.
- **`user_memories` vector-only (design-consistent).** No lexical blend because P2-04 gave that table no `tsvector`/GIN column and LangMem recalls by semantic proximity — matches §5.4 and the task's explicit allowance. No action.
- **Logged follow-up (not blocking): ANN prefilter deferred.** `hybrid_search_chunks` uses an exact full-precision cosine scan; the P2-04 `binary_quantize(...)::bit(4096) bit_hamming_ops` HNSW index is the intended top-N prefilter at scale (same result contract). Consistent with the P2-04 flag that 4096 dims exceed pgvector's ANN cap. Correct for current data; revisit when corpus grows (P4/P5 or later).
- **Logged follow-up (not blocking): Qwen3 query-instruction task string.** `DEFAULT_QUERY_TASK` uses the model-card generic-retrieval instruction and is a constructor arg; the exact wording should be tuned against the career KB before production embedding, as the engineer noted. The instruction *format* is confirmed; not a design risk.
