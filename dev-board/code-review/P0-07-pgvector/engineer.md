# Engineer report — P0-07-pgvector · Revision 1

## Summary
Wired the pgvector `vector` extension into the Postgres container so it is enabled
automatically on first cluster init. Added a Postgres init SQL script, mounted the
init directory into the `db` service via docker-compose, and added a dependency-free
dev smoke-test script that reports extension presence via exit code. Verified the
full flow live against the real `pgvector/pgvector:pg16` image (fresh volume,
re-init, positive and negative paths).

## Files changed
- `backend/migrations/init/01_enable_pgvector.sql` (new) — `CREATE EXTENSION IF NOT EXISTS vector;` only; documents that init scripts run once on empty-volume init and that table/column DDL is deferred to Alembic in P2.
- `docker-compose.yml` — added a read-only bind mount on the `db` service: `./backend/migrations/init` → `/docker-entrypoint-initdb.d`, so the official Postgres entrypoint runs the SQL on first init.
- `backend/scripts/check_pgvector.py` (new) — async smoke-test using `asyncpg` (already a backend dep). Resolves connection from `DATABASE_URL` (strips SQLAlchemy `+asyncpg`/`+psycopg` suffixes) or `POSTGRES_*` parts; loads a local `.env` without overriding real env vars. Exit codes: 0 = `pgvector OK`, 1 = `pgvector MISSING`, 2 = connection/config error.

## Key decisions
- **Init via `/docker-entrypoint-initdb.d` bind mount, not a custom image** — the official Postgres entrypoint already runs `*.sql` there on first init; no Dockerfile needed. Mounting the whole `init/` dir (not a single file) lets future init scripts drop in (still bounded: table DDL stays in Alembic per task constraint + app-design §7). Mount is `:ro` since the container only reads it.
- **Extension only, no tables** — honors the task non-goal and the P2 Alembic boundary; `vector(4096)` columns (`kb_chunks`, `user_memories`) come later (app-design §7).
- **Smoke-test uses `asyncpg` directly, not `app.config.settings`** — importing `settings` would raise on missing `HF_API_TOKEN`/`JWT_SECRET_KEY`, which are irrelevant to a DB connectivity check. Keeping the script self-contained (manual `.env` parse, no new dep) means it runs from the host after `docker compose up`.
- **Defensive `Path.parents` indexing** — found during live testing that a shallow path crashed module load; guarded so the script can't fail at import regardless of where it sits.
- **No hard-coded credentials** — compose uses `${POSTGRES_*}` interpolation; the script reads env/`.env`. Nothing secret committed.

## How to verify
From the repo root with a populated `.env` (`POSTGRES_USER/PASSWORD/DB`):
```bash
docker compose up -d db                       # entrypoint runs init SQL on first start
python backend/scripts/check_pgvector.py      # -> "pgvector OK", exit 0
# fresh-volume re-init still enables it:
docker compose down -v && docker compose up -d db
python backend/scripts/check_pgvector.py      # -> "pgvector OK", exit 0
```
Direct check inside the container:
```bash
docker exec <db-container> psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -tAc "SELECT extname FROM pg_extension WHERE extname='vector';"   # -> vector
```

### Live test results (isolated compose project `p007test`, real pgvector/pgvector:pg16)
- Fresh volume up → `psql` query returns `vector`. ✅
- Smoke-test against the enabled DB → prints `pgvector OK`, `EXIT=0`. ✅
- Smoke-test against a DB without the extension → prints `pgvector MISSING`, `EXIT=1`. ✅
- `docker compose down -v && up` (fresh volume) → extension re-enabled, returns `vector`. ✅
- `docker compose config` renders the init mount with `read_only: true`. ✅
- `python -m py_compile backend/scripts/check_pgvector.py` → OK.
- Test stack torn down with `down -v` (no residue).

## Self-check
- [x] Meets acceptance criteria (all 5 verified live, see above)
- [x] No secrets committed; layering N/A (infra/init + dev script, no Router/Service/Repo code touched)
- [x] Tests/lints pass — `py_compile` OK; `docker compose config` OK; live extension checks pass (results pasted above)

## Notes
- The init script only runs when the `postgres_data` volume is empty. On an existing dev volume created before this task, run `docker compose down -v` once (or `CREATE EXTENSION IF NOT EXISTS vector;` manually) to pick it up. This is standard Postgres init behavior and is documented in the SQL header.
- The smoke-test is a dev utility only; CI wiring is P0-09 per the task.
