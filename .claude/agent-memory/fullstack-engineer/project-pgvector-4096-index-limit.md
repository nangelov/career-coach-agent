---
name: pgvector-4096-index-limit
description: pgvector HNSW/IVFFlat cannot index the locked vector(4096) embeddings; use binary_quantize bit_hamming ANN + exact cosine rerank
metadata:
  type: project
---

The locked embedding dim is **vector(4096)** (`Qwen/Qwen3-Embedding-8B`, design §6 item 3),
but **pgvector ANN indexes cannot index 4096-dim vectors**: HNSW/IVFFlat cap at **2000 dims
for `vector`** and **4000 for `halfvec`**. `bit` supports up to 64000.

**Why:** a plain `USING hnsw (embedding vector_cosine_ops)` index fails at CREATE time with
`column cannot have more than 2000 dimensions for hnsw index` (halfvec: 4000). This is a hard
pgvector limit, not a config knob.

**How to apply (established in P2-04 migration `0003`):**
- Keep the column full-precision `vector(4096)` (locked — do not truncate).
- ANN index = HNSW over binary quantization:
  `CREATE INDEX ... USING hnsw ((binary_quantize(embedding)::bit(4096)) bit_hamming_ops)`.
  It's a **functional/expression index** — create it via raw `op.execute(...)` in the migration
  (not expressible via `mapped_column`/ORM `Index`), and add its name to `_UNMODELED_INDEXES`
  in `migrations/env.py`'s `include_object` filter or autogenerate proposes dropping it (drift).
- Exact cosine (`ORDER BY embedding <=> :q`) runs on the full column and is what the P2 exit
  query + the hybrid-search **rerank** step use. The bit index only accelerates the candidate
  prefilter (Hamming), so the `llm/embeddings.py` hybrid query must be: bit-Hamming ANN top-N →
  rerank by exact cosine → blend with `ts_rank` (GIN on generated `content_tsv`).
- Lexical half is a generated `content_tsv` STORED column + GIN index (already in schema).
