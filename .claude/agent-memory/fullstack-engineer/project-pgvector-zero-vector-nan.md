---
name: project-pgvector-zero-vector-nan
description: pgvector cosine distance is NaN for a zero vector — dedup/similarity integration tests need a non-zero constant embedding
metadata:
  type: project
---

pgvector's cosine distance (`<=>`) is **undefined (NaN)** for an all-zero vector, so
`1 - cosine_distance` between two zero embeddings is NaN — never `>= threshold`.

**Why:** cosine similarity divides by the vector norm; a zero vector has norm 0.

**How to apply:** a fake embedder used in a **live-Postgres** test that must exercise a
similarity/dedup branch (e.g. the P9-03 learn near-duplicate path) must return a **non-zero**
constant (e.g. `[0.1]*4096`), not `[0.0]*4096`. Two identical non-zero vectors → cosine
similarity 1.0, which is what the dedup threshold check needs. `[0.0]*DIM` is fine only for
insert/persist tests that never search.
