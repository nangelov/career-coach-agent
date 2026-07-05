# Architecture review — P2-04-migration-knowledge · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure / layering | Models in `repositories/models/<group>.py`, migration in `migrations/versions/`; repository layer only | `models/knowledge.py` + `20260705_0003_knowledge_and_vectors.py`; no service/router/api touched | None — matches P2-03 subpackage convention (blessed, not re-litigated) |
| A2 | §4 table list | `kb_documents`, `kb_chunks(embedding vector)`, `user_memories(embedding vector)` | All three tables present with the specified columns | None |
| A3 | §6 item 3 embedding dim | `vector(4096)` (full Qwen3-Embedding-8B output), no truncation | Both `embedding` columns `Vector(4096)`; `EMBEDDING_DIM=4096` constant in model + migration | None — lock honored (see Notes on the ANN-index resolution) |
| A4 | §4 datastore posture | Postgres + pgvector + JSONB only, self-hosted | JSONB `metadata` (not JSON), pgvector column, extension bootstrapped by P0-07 init script (not in migration) | None |
| A5 | §4 GDPR delete posture | user-scoped rows erased on user-delete; shared curated content survives | `kb_documents.user_id` (nullable) + `user_memories.user_id` `ON DELETE CASCADE`; NULL `user_id` = shared, survives; chunk cascade via parent doc | None |
| A6 | §5.5 message linkage | `source_message_id` references the stable app-level `messages.message_id` | FK to `messages.message_id` `String(32)`, `ON DELETE SET NULL` | None — consistent with P2-03 `message_id = String(32)` + SET-NULL-outlives-message ruling |
| A7 | enum posture (P2-03 ruling) | `String` + `CheckConstraint`, not native PG ENUM | `source_type`/`memory_type` as checked `String` | None — kept in lockstep with the P2-03 `role`/`rating` posture |
| A8 | hybrid-search groundwork (tasks.md P2) | tsvector + GIN (lexical) and cosine ANN index (vector) present, scoring deferred | Generated STORED `content_tsv` + GIN `ix_kb_chunks_content_tsv`; binary-quantize HNSW ANN on both embeddings; no scoring code | None — schema-ready, weights correctly left to `llm/embeddings.py` |
| A9 | phase fit | schema-only; no LangMem (P9), no EmbeddingClient, no jobs/pdp tables (P2-05) | `user_memories` schema-only; no LangMem wiring; no embeddings code; no dashboard tables | None — scoped correctly, no premature coupling |
| A10 | migration chain | `down_revision` chains onto P2-03 head | `revision="0003"`, `down_revision="0002"`; downgrade drops in reverse dependency order | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — repository/migration layer only, no cross-layer leak
- [x] Honors locked decisions — Postgres+pgvector only (no Mongo), `vector(4096)` un-truncated, JSONB, self-hosted (extension via init script), enums as CheckConstraint
- [x] Interfaces-before-implementations — N/A (schema task); does not block the upcoming `EmbeddingClient`/hybrid-search seam, and demonstrably enables it (both index types present)
- [x] Budget posture respected — free/OSS/self-hosted pgvector; no managed tier, no API cost introduced

## Notes
- **Binary-quantize HNSW ANN index (the engineer's flag) — accepted as the correct design resolution, not a lock violation.** pgvector caps HNSW/IVFFlat at 2000 dims for `vector` (4000 for `halfvec`); the locked 4096 dim (§6 item 3) forbids truncation *here*. The engineer kept the full-precision `vector(4096)` column and built the ANN index over `binary_quantize(embedding)::bit(4096) bit_hamming_ops` (the pgvector-documented >4000-dim pattern), with **exact cosine** (`ORDER BY embedding <=> :q`) still running on the full-precision column — which is the P2 exit-criterion query and the future hybrid rerank. This preserves the locked dimension *and* correctness, and is precisely the "documented-alternative cosine-ops index" the acceptance criterion permits. §6 item 3 already reserves Matryoshka truncation as an explicit-migration-only future change, so no dimension decision is being reopened. **Design ruling: this two-stage pattern (bit-Hamming ANN prefilter → exact-cosine rerank on the full column) is the blessed approach for 4096-dim vectors under pgvector.**
- **Follow-up for `llm/embeddings.py` (next task), not blocking:** the hybrid query must be written against this two-stage reality — the HNSW index accelerates a *candidate* prefilter via Hamming≈cosine on unit vectors, and final ranking must rerank on exact cosine over `embedding`. Whoever writes the weighted blend should not assume the HNSW index directly orders by cosine. Logged so it isn't a surprise.
- `env.py` `include_object` filter excluding the two functional indexes is the standard Alembic pattern for expression indexes it cannot round-trip; drift check confirmed it keeps autogenerate quiet without masking table/column drift. Acceptable and correctly scoped.
- Live-Postgres verification (upgrade/downgrade/no-drift + cosine NN on both tables) satisfies the P2 exit criterion ahead of the dedicated exit-verify task; CI-skip posture matches P2-02/03.
