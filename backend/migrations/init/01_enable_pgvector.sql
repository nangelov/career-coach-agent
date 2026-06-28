-- Career Coach Agent v2 — Postgres init script (runs once, on first cluster init).
--
-- Files in this directory are mounted into the pgvector/pgvector:pg16 container at
-- /docker-entrypoint-initdb.d/ and executed by the official Postgres entrypoint in
-- lexical order the FIRST time the data volume is empty. They do NOT run again on
-- subsequent starts of an already-initialised volume (use `docker compose down -v`
-- to force a fresh re-init).
--
-- Scope (P0-07): enable the pgvector extension only. Table/column creation
-- (kb_chunks.embedding vector(4096), user_memories.embedding vector(4096)) is
-- handled by Alembic migrations in P2 — see dev-board/app-design-and-features.md §7.

CREATE EXTENSION IF NOT EXISTS vector;
