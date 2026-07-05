# Task P2-04-migration-knowledge — Migration: knowledge/vectors (pgvector)
- **Phase:** P2   **Status:** ENG   **Tags:** (B)

## Scope
Add the **second real Alembic migration**, on top of P2-03's `0002` (identity/docs), covering the
**knowledge/vectors** table group (design §4 "Postgres + pgvector — knowledge, memory & structured
records"), plus the ORM models. Follow the same `repositories/models/` subpackage convention P2-03
established (add a new module, e.g. `models/knowledge.py`, and register it in `models/__init__.py`).

Tables:
- `kb_documents` — RAG knowledge-base source documents (curated career/learning content, and the parsed
  source of a user's own CV once ingested — §5.1): id, `title`, `source` (e.g. URL or "user-cv"),
  `source_type` (enum/checked varchar: e.g. `curated` | `user_cv` | `crawled`), owning `user_id` (nullable
  FK to `users.id` — **null for shared/curated KB content**, set for a user's private CV-derived doc),
  `content` (raw text, nullable — large docs may prefer chunk-only storage; your call, document it),
  `metadata JSONB`, `created_at`, `updated_at`.
- `kb_chunks` — the retrieval unit: id, `kb_document_id` FK (cascade-delete with the parent document),
  `chunk_index` (ordering within the document), `content` text, **`embedding vector(4096)`** (dimension
  fixed by `Qwen/Qwen3-Embedding-8B`, §6 item 3 — do not use a different dimension), `metadata JSONB`,
  `created_at`.
- `user_memories` — teachable per-user memory (§5.4/§5.5/§6.7, the store **LangMem** will manage in P9):
  id, `user_id` FK (cascade-delete — GDPR view/delete posture, §4), `text` (the learned fact), **`embedding
  vector(4096)`**, `memory_type` (checked varchar, e.g. `preference` | `fact` | `style`), `confidence`
  (float), `source_message_id` (nullable, references `messages.message_id` — the turn the memory was
  learned from), `created_at`, `updated_at`.

### Hybrid search — anticipate it now, don't implement it here
`dev-board/tasks.md` calls for the upcoming `llm/embeddings.py` task (next after this one) to do
**"Hybrid Search with weights"** (combining vector similarity with lexical/full-text signals, weighted),
and the P2 exit-verification task to demonstrate a weighted similarity query. This migration's job is to
make sure the **schema doesn't block that** — do not implement the search logic here, just the columns/
indexes it will need:
- Add a **generated `tsvector` column** (Postgres `GENERATED ALWAYS AS (to_tsvector('english', content))
  STORED`, or a plain `tsvector` column maintained via trigger if you prefer — document the choice) on
  `kb_chunks.content` for lexical/full-text search, with a **GIN index** on it.
- Add a **vector index** on `kb_chunks.embedding` and `user_memories.embedding` — prefer **HNSW**
  (`pgvector`'s `vector_cosine_ops`) over IVFFlat since HNSW needs no training data and this table starts
  empty; document why if you choose otherwise. Use cosine distance ops since the design specifies cosine
  similarity (P2's exit criterion: "cosine similarity query returns expected neighbor").
- These two indexes (GIN full-text + HNSW vector) are exactly what a later weighted hybrid-search query
  (e.g. reciprocal-rank-fusion or a weighted linear blend of `1 - cosine_distance` and `ts_rank`) would
  scan — confirm in `engineer.md` that both index types are present and usable, but leave the actual
  scoring/weights to the `llm/embeddings.py` task.

## Build
- ORM models via SQLAlchemy 2.x `Mapped`/`mapped_column`, using `pgvector.sqlalchemy.Vector(4096)` for the
  embedding columns (the `pgvector` Python package is already a dependency per `pyproject.toml` — confirm
  it exposes a SQLAlchemy type; if the installed version's SQLAlchemy integration differs, document the
  exact import path used).
- Alembic migration (`alembic revision --autogenerate -m "knowledge and vector tables"`, `down_revision`
  = P2-03's identity migration) — hand-review the generated DDL as P2-03 did (autogenerate often needs
  correction for generated columns, custom index methods like `USING hnsw`/`USING gin`, and vector column
  types — verify these emit correctly, fixing by hand in the migration file if autogenerate doesn't express
  them faithfully).
- Confirm `env.py`'s model import (added in P2-03 so autogenerate sees `Base.metadata`) picks up the new
  `knowledge.py` module once it's registered in `models/__init__.py`.

## Verification
- Live-Postgres verification (same posture as P2-02/03): `alembic upgrade head` / `alembic downgrade` to
  the prior revision, both clean; confirm `\d kb_chunks` (or equivalent introspection) shows the `vector`
  column, the GIN tsvector index, and the HNSW vector index.
- An integration test (real Postgres — JSONB/pgvector aren't available in SQLite) that: inserts a
  `kb_document` + a few `kb_chunks` with distinct embeddings, and runs an actual **cosine similarity query**
  (`ORDER BY embedding <=> :query_vector LIMIT k`) proving the nearest neighbor is the expected row (e.g.
  insert one chunk with an embedding close to a probe vector and others far away, assert it's returned
  first). This directly proves the P2 exit criterion ("vector insert + similarity query verified") for this
  table, ahead of the dedicated exit-verify task.
- Also insert a `user_memories` row and confirm the same query pattern works against it.
- `ruff` + `mypy` clean.

## Acceptance criteria
- [ ] `kb_documents`, `kb_chunks`, `user_memories` ORM models + migration exist, chained after P2-03.
- [ ] `kb_chunks.embedding` and `user_memories.embedding` are `vector(4096)` (pgvector), matching
      `Qwen/Qwen3-Embedding-8B`'s output dimension.
- [ ] `kb_chunks` has a full-text `tsvector` column + GIN index, and both vector columns have an HNSW
      (or documented-alternative) cosine-ops index — schema-ready for the next task's hybrid search.
| [ ] `user_memories.user_id` cascade-deletes with the user (GDPR posture, §4).
- [ ] A live insert + cosine-similarity query test demonstrates correct nearest-neighbor ordering on at
      least `kb_chunks` (and ideally `user_memories`).
- [ ] `alembic upgrade`/`downgrade` verified clean against the live Postgres container.
- [ ] `ruff` + `mypy` clean.

## Design references
- dev-board/app-design-and-features.md §4 (table list), §5.4/§5.5 (user_memories), §6 item 3 (embedding
  dim = 4096), §6.7 (LangMem will manage `user_memories` later — this task only builds the table)
- dev-board/tasks.md P2 section — the "Hybrid Search with weights" / "add extra weighting" notes on the
  next two checklist items, motivating the tsvector + index groundwork here
- dev-board/code-review/P2-03-migration-identity/engineer.md — the `repositories/models/` subpackage
  convention, migration numbering, and autogenerate-then-hand-review process to repeat
- backend/pyproject.toml — confirm `pgvector` package version/API before assuming a specific import path

## Constraints / non-goals
- No `jobs`/`pdps`/dashboard tables here — that's the next migration task (P2-05).
- No `llm/embeddings.py` / `EmbeddingClient` code here — that's the task immediately after this one; this
  task only makes sure the schema (columns + indexes) doesn't block it.
- No LangMem wiring (P9) — `user_memories` is schema-only here.
