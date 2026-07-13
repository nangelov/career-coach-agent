---
name: project-live-docker-stack
description: A live docker-compose stack (Postgres+pgvector, Redis, backend, worker, frontend) is usually already running in this sandbox — use it to functionally verify infra/DB tasks
metadata:
  type: project
---

The full docker-compose stack is *often* already up in this environment: containers
`career-coach-agent-db-1` (pgvector/pgvector:pg16, port 5432), `-redis-1` (6379),
`-backend-1`, `-worker-1`, `-frontend-1`. Check with `docker ps` — but it is **not
guaranteed** (found down for SEC-05). If down and you need real Postgres, bring up just
the db and migrate, then tear down when finished (leave as found):
`docker compose -f docker-compose.yml -f docker-compose.dev-ports.yml up -d --wait db`,
then `alembic upgrade head` (under the LIVE_DB_ENV DSN below), run pytest, then
`docker compose -f docker-compose.yml down`. The dev-ports override publishes 5432 (the
default compose keeps it internal-only per §7.2).

**Why:** the local `backend/.venv` is partial (see [[project-local-venv-partial]]) and
the WSL system Python has no deps (see [[feedback-system-python-no-deps]]), so a task
that says "verify against a real Postgres if available" often *is* available here.

**How to apply:** for DB/infra tasks, prefer verifying against the live container over a
SQLite dry-run. Build a host DSN from the root `.env` creds pointing at `localhost` (the
db container publishes 5432), e.g.
`postgresql+asyncpg://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:5432/$POSTGRES_DB`.
Source secrets with `set -a && . ./.env && set +a` (root `.env`, not `backend/.env` —
the latter doesn't exist). Inspect DB state directly with
`docker exec career-coach-agent-db-1 psql -U $POSTGRES_USER -d $POSTGRES_DB -c "..."`.
The `vector` extension is already installed in that db (P0-07 init script).
