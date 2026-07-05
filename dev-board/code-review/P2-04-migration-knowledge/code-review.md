# Code review — P2-04-migration-knowledge · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/migrations/versions/20260705_0003_knowledge_and_vectors.py:144 | The `ix_*_embedding_hnsw` binary-quantize indexes are created but no query in this task (or the P2 exit test) uses them — the cosine queries all run `embedding <=> :q` on the full-precision column, which seq-scans. The index is present-but-dormant until `llm/embeddings.py` writes a Hamming-prefilter query. This is correct for a schema-only task; noting so the next task actually wires the ANN path rather than assuming the index is already exercised. | None required here — carry into `llm/embeddings.py`. |
| C2 | nit | backend/tests/test_knowledge_models.py:42 | `_postgres_reachable()` opens a throwaway engine/connection, then the fixture opens a second engine for the real work — two connect round-trips per test. Harmless; could reuse one engine. | Optional cleanup. |

## Notes
Reviewed the full diff and ran the engineer's verification live against the running
`career-coach-agent-db-1` (pgvector 0.8.2) container:

- `alembic downgrade 0002` → `upgrade head` both clean; `alembic check` → **"No new upgrade
  operations detected"** (drift-clean, confirming the `env.py` `include_object` filter neither
  hides real changes nor spuriously proposes dropping the functional indexes).
- `\d kb_chunks` confirms `embedding vector(4096)`, `content_tsv tsvector ... GENERATED ALWAYS AS
  (to_tsvector('english', content)) STORED`, the GIN index on `content_tsv`, and the HNSW
  `((binary_quantize(embedding)::bit(4096)) bit_hamming_ops)` index. `user_memories` matches.
- `pytest tests/test_knowledge_models.py` → **9 passed**; `ruff check`/`ruff format --check` clean;
  `mypy app/ migrations/` → success, 39 files.

Correctness/quality checks that passed:
- **FK type/target match:** `user_memories.source_message_id String(32)` → `messages.message_id
  String(32)` (unique natural key) — types and uniqueness align, FK is valid.
- **Cascade posture matches design §4 GDPR:** `kb_documents.user_id` / `user_memories.user_id`
  `ON DELETE CASCADE` (verified via `test_user_cv_document_cascades_with_user` — private CV doc
  erased, shared curated doc with NULL `user_id` survives); `source_message_id ON DELETE SET NULL`
  verified detaching memory without destroying it. Deletes rely on DB-level cascade (no ORM
  relationship from `User`), and the live tests prove the DB enforces it.
- **Downgrade drops in correct reverse-dependency order** (user_memories → kb_chunks → kb_documents),
  named functional HNSW indexes dropped explicitly.
- **Embedding dim locked at 4096** on both vector columns (`EMBEDDING_DIM` single source), honoring
  the §6 lock rather than truncating.
- **No `CREATE EXTENSION`** in the migration (pgvector bootstrapped by the P0-07 init script) —
  boundary respected. Check constraints are static DDL; no untrusted input reaches the schema.
- Security: no secrets, no dynamic SQL from user input; all DDL is literal.

**Out of my lane (flagged for the system-architect, not gated here):** the substantive deviation is
using a `binary_quantize(...)::bit(4096) bit_hamming_ops` HNSW index instead of `vector_cosine_ops`
HNSW, forced by pgvector's 2000-dim (`vector`) / 4000-dim (`halfvec`) index cap vs the locked 4096
dimension. The engineer flagged this for an explicit §6/design ruling. From a correctness standpoint
it is sound (exact cosine still runs on the full-precision column and the P2 exit test proves correct
NN ordering); whether the Hamming-prefilter-then-cosine-rerank strategy is the right design
resolution — vs Matryoshka-truncated 2000-dim index or exact-scan-only — is the architect's call.
