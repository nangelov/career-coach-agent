# Task P0-07-pgvector — Wire pgvector extension into the Postgres image/init

- **Phase:** P0   **Status:** ENG   **Tags:** (I)

## Scope

Ensure the `pgvector/pgvector:pg16` Postgres container automatically enables the `vector` extension on startup:

1. Create `backend/migrations/init/01_enable_pgvector.sql` containing `CREATE EXTENSION IF NOT EXISTS vector;`
2. Mount this SQL file (and any future init scripts) into the Postgres container at `/docker-entrypoint-initdb.d/` via a `docker-compose.yml` volume bind so Postgres runs it on first start.
3. Add a connection-level smoke-test: a `backend/scripts/check_pgvector.py` script that connects to Postgres (using env vars from `.env`) and runs `SELECT extname FROM pg_extension WHERE extname = 'vector';` — exits 0 if found, 1 if not.

## Acceptance criteria

- [ ] `backend/migrations/init/01_enable_pgvector.sql` exists with `CREATE EXTENSION IF NOT EXISTS vector;`.
- [ ] `docker-compose.yml` mounts `./backend/migrations/init/` → `/docker-entrypoint-initdb.d/` for the `db` service.
- [ ] After `docker compose up`, running the smoke-test script exits 0 and prints `pgvector OK`.
- [ ] `docker compose down -v && docker compose up` (fresh volume) still enables the extension on re-init.
- [ ] No hard-coded credentials in any new file.

## Design references

- `dev-board/plan.md` — P0 "Local infra: Wire pgvector extension"
- `dev-board/app-design-and-features.md` — §7 data model (`kb_chunks(embedding vector(4096))`, `user_memories(embedding vector(4096))`)
- `docker-compose.yml` (P0-06, already done)
- `backend/app/config.py` — DB connection settings (P0-03)

## Constraints / non-goals

- Full Alembic migration setup is P2; this task only ensures the extension exists.
- No table creation in the init SQL — just the extension.
- The smoke-test script is a dev utility only; it is not wired into CI here (that is P0-09).
