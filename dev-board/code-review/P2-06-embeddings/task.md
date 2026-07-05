# Task P2-06-embeddings — `llm/embeddings.py`: EmbeddingClient + pgvector hybrid search
- **Phase:** P2   **Status:** ENG   **Tags:** (B)

## Scope
Build `app/llm/embeddings.py` — the **in-process embedding client** (§6 item 3: `Qwen/Qwen3-Embedding-8B`
via `sentence-transformers`, 4096-dim output, no external API) — plus the **pgvector write and
hybrid-search helpers** that sit on top of P2-04's `kb_chunks`/`user_memories` tables (which already have
the `vector(4096)` column, the generated `tsvector` + GIN index, and the bit-quantized HNSW ANN index).
`dev-board/tasks.md` explicitly calls for **"Hybrid Search with weights"** here — implement it, don't defer
it further.

### 1. `EmbeddingClient`
- An ABC/interface (`EmbeddingClient`) with an async `embed(texts: list[str]) -> list[list[float]]` (or
  similar batched signature) plus a documented `DIMENSION = 4096` constant, mirroring the ports-and-adapters
  pattern already used for `LLMClient` (P1-01) and `SessionMemory`/`CancelRegistry` (P1-05/06): the
  interface lives in `app/llm/embeddings.py`, any heavy/real implementation detail stays swappable.
- A concrete `SentenceTransformerEmbeddingClient` wrapping `sentence_transformers.SentenceTransformer`
  loaded with `settings.EMBEDDING_MODEL` (`Qwen/Qwen3-Embedding-8B`, already in `app/config.py`).
  **Critical constraints, read before writing any code:**
  - `sentence-transformers`/`torch` are **deliberately excluded** from the backend CI curated install (see
    `.github/workflows/backend-ci.yml`'s comment block) — a full 8B-param model cannot download or run in
    CI or in this sandboxed dev environment. **Lazy-load the model** (construct the `SentenceTransformer`
    only on first `embed()` call, not at import time or client-construction time) so importing
    `app/llm/embeddings.py` and constructing the client never triggers a download — mirrors how
    `HFOpenAICompatibleClient` (P1-01) doesn't connect at construction.
  - Since the real model cannot run here, the encode step must be **behind an injectable seam** so tests
    can substitute a small deterministic fake (e.g. a hash-based or random-but-seeded vector generator
    returning `DIMENSION`-length floats) — do not attempt to actually download/run
    `Qwen/Qwen3-Embedding-8B` in tests or in this environment. Document this limitation exactly like prior
    tasks documented "no live HF token" cases.
  - `sentence-transformers` isn't in the CI curated install, so it'll be typed as `Any` via mypy's
    `ignore_missing_imports` (same posture as `langgraph`/`docling`/`alembic`) — keep first-party code
    around it fully typed regardless.
  - Qwen3 embedding models typically need query/document instruction prefixes for best retrieval quality
    (check the model card conventions if you have web access; if not, implement a simple, documented
    `embed_query(text)` vs `embed_documents(texts)` split with a placeholder/no-op prefix and leave a
    `# TODO` noting the exact instruction-prefix string should be confirmed against the model card before
    this touches production embeddings — don't block the task on this, just don't silently ignore it
    either).

### 2. pgvector write helpers
- A repository-layer function (e.g. in `app/repositories/postgres.py` or a new
  `app/repositories/vector_search.py` — your call, document it, but keep DB access in `repositories/` per
  §8 "services never touch drivers directly") to **insert/upsert** a `kb_chunks` row (or `user_memories`
  row) given its text + a precomputed embedding — i.e. wire the `EmbeddingClient` output into the P2-04
  schema. Don't reinvent the ORM models; use the ones P2-04 already defined
  (`app.repositories.models.knowledge`).

### 3. Hybrid search with weights
- A similarity-search helper, e.g. `hybrid_search(query: str, *, k: int, vector_weight: float = 0.5,
  text_weight: float = 0.5, ...) -> list[SearchResult]` that:
  - embeds `query` via the `EmbeddingClient`,
  - runs a single SQL query combining **cosine similarity** (`1 - (embedding <=> :q)`) and **lexical rank**
    (`ts_rank(content_tsv, plainto_tsquery('english', :query))` against the generated `tsvector` column
    P2-04 built) into one weighted score — e.g. `vector_weight * cosine_sim + text_weight * ts_rank_norm`
    (normalize `ts_rank` into a comparable [0,1]-ish range before blending, or use a documented alternative
    such as reciprocal-rank-fusion of the two ranked lists if you judge that more robust — **document
    whichever blending strategy you pick and why**, since "weights" is an explicit design ask, not just
    top-k vector search),
  - returns results ordered by the combined weighted score, `LIMIT k`.
  - The weights must be **caller-configurable parameters** (not hardcoded constants) — this is what
    "weights" means in the task title; a sensible default (e.g. 0.5/0.5) is fine.
  - Works against both `kb_chunks` and (if the schema differs enough — `user_memories` doesn't have a
    tsvector column per P2-04) at minimum `kb_chunks`; if `user_memories` similarity search is needed too,
    a **vector-only** search helper for it is acceptable (document why hybrid doesn't apply there — no
    lexical index on that table yet).

## Verification
- Live-Postgres integration test (real DB via docker-compose, since JSONB/pgvector/tsvector don't exist in
  SQLite): insert a handful of `kb_chunks` with controlled fake embeddings (via the injectable fake, not
  the real model) and distinct text content, then call `hybrid_search` with different weight combinations
  and assert the ranking changes sensibly (e.g. a chunk that's lexically an exact match but vector-distant
  ranks higher when `text_weight` dominates, and vice versa) — this is the actual proof the weighting
  works, not just that a query executes.
- A `test_embeddings.py` unit test for `EmbeddingClient`'s interface/seam (using the fake encoder), and a
  separate test module for the pgvector write + hybrid-search helpers (real Postgres, following the
  pattern from `test_identity_models.py`/P2-04's knowledge test — skip cleanly if no DB reachable, same as
  prior tasks).
- `ruff` + `mypy` clean.

## Acceptance criteria
- [ ] `app/llm/embeddings.py` defines an `EmbeddingClient` interface + a
      `SentenceTransformerEmbeddingClient` implementation; model load is lazy (no download at import/
      construction time).
- [ ] A documented, injectable seam lets tests substitute a fake encoder — no attempt to run the real
      8B-param model in CI/this sandbox.
- [ ] A pgvector write helper inserts embeddings into `kb_chunks`/`user_memories` using the P2-04 ORM
      models (no duplicated/parallel model definitions).
- [ ] A `hybrid_search` helper blends cosine similarity + lexical rank with **caller-configurable weights**,
      backed by a real query against a live Postgres in the test suite, demonstrating weight changes
      actually change ranking.
- [ ] `ruff` + `mypy` clean.

## Design references
- dev-board/app-design-and-features.md §6 item 3 (embedding model/dim), §4 (pgvector tables)
- dev-board/tasks.md P2 section — "use Hybrid Search with weights" (this task) and "add extra weighting"
  (the next, exit-verification task, which will build on what this task delivers)
- dev-board/code-review/P2-04-migration-knowledge/engineer.md — the exact `kb_chunks`/`user_memories`
  schema (Vector(4096) columns, generated `content_tsv` + GIN index, bit-quantized HNSW index) this task
  builds on
- dev-board/code-review/P1-01-llm-client/engineer.md — the `LLMClient` ports-and-adapters precedent this
  `EmbeddingClient` interface should mirror

## Constraints / non-goals
- No LangMem wiring (P9) — this is the low-level embedding + search primitive LangMem's `user_memories`
  store will eventually sit on, not LangMem itself.
- No RAG agent / retrieval tool-calling integration (P4/P5) — this task delivers the reusable
  embed-and-search primitive only.
- Do not attempt to actually download or run `Qwen/Qwen3-Embedding-8B` in this sandboxed environment or in
  CI — use the injectable fake-encoder seam for all automated verification, and document this limitation
  clearly (same posture as prior tasks' "no live HF token" caveats).
