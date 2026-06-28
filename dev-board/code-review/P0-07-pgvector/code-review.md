# Code review — P0-07-pgvector · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | backend/scripts/check_pgvector.py:89 | DSN is built by f-string interpolation (`postgresql://{user}:{password}@...`). A password/user containing URL-special chars (`@ : / # ?`) corrupts the DSN and asyncpg will misparse it, surfacing as a confusing exit-2 "could not connect". | Prefer passing discrete kwargs to `asyncpg.connect(user=, password=, database=, host=, port=)` for the `POSTGRES_*` path (and `urllib.parse.quote` if keeping URL form). Dev-utility only — defer is acceptable. |
| C2 | minor | backend/scripts/check_pgvector.py:61-66 | When `DATABASE_URL` is populated with the compose-internal host (`@db:5432`) it is used verbatim, so running the smoke-test from the host fails to connect (exit 2). | Note only: the default `.env.example` leaves `DATABASE_URL` commented and falls back to the `localhost` `POSTGRES_*` path, so the documented happy path works. Consider a `--host` override or a comment warning. |

## Notes
- Verified independently: `01_enable_pgvector.sql` contains exactly `CREATE EXTENSION IF NOT EXISTS vector;` (no table DDL — honors the P2/Alembic boundary and app-design §7); `docker-compose.yml` mounts `./backend/migrations/init → /docker-entrypoint-initdb.d:ro` on the `db` service; `python3 -m py_compile backend/scripts/check_pgvector.py` passes; `asyncpg>=0.29.0` is a declared backend dep (`backend/pyproject.toml:16`), so no new dependency was introduced. The engineer's pasted live results (fresh-volume init, re-init after `down -v`, positive + negative smoke-test paths) cover all acceptance criteria.
- No hard-coded credentials: compose uses `${POSTGRES_*}` interpolation; the script reads env/`.env`. `.env.example` ships placeholder dev creds only.
- `backend/scripts/__pycache__/*.pyc` is git-ignored (confirmed via `git check-ignore`) — not a finding.
- The `.env` loader is dependency-free and correctly (a) preserves real env vars over file values and (b) keeps `#` inside values (partitions on the first `=`), so passwords containing `#` survive. Quote-stripping is reasonable for a dev utility.
- The large `docker-compose.yml` diff (db/redis/backend/worker/frontend services, volumes) is P0-06 scope, not P0-07; only the init-dir bind mount belongs to this task. The P0-06 content was not re-reviewed here. Design-conformance of the service layout is the system-architect's call.

## Verdict: APPROVED
