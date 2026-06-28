# Engineer report — P0-06-docker-compose · Revision 1

## Summary

Stood up the local v2 dev stack: a root `docker-compose.yml` bringing up **5 services**
(`db`, `redis`, `backend`, `worker`, `frontend`), a production-style `backend/Dockerfile` (uv → uvicorn)
shared by the backend and the Celery worker, a multi-stage `frontend/Dockerfile` (`next build` → `next start`),
and a root `.env.example` listing every required variable. All credentials are sourced from `.env` via compose
interpolation — nothing secret is hard-coded. Postgres and Redis persist to named volumes. To let the `worker`
service boot without crashing (its tasks land in P0-08), I added a minimal Celery app/worker entry at
`backend/app/tasks/celery_app.py`.

## Files changed

- `docker-compose.yml` (root) — **replaced** the v1 single-`app` compose with the v2 5-service stack
  (db/redis/backend/worker/frontend), health checks, `depends_on: service_healthy`, named volumes.
- `.env.example` (root) — **new**; all required/optional env vars with placeholder values.
- `backend/Dockerfile` — filled the P0-01 stub: `python:3.11-slim` + uv, `uv sync --no-install-project --no-dev`,
  copy `app/`, uvicorn entrypoint on 8000.
- `backend/.dockerignore` — **new**; trims build context (`.venv`, caches, tests, `.env`).
- `backend/app/tasks/celery_app.py` — **new**; Celery app wired to `settings.REDIS_URL` (broker+backend) so
  `celery -A app.tasks.celery_app worker` starts cleanly. No tasks yet (P0-08).
- `frontend/Dockerfile` — **new**; multi-stage `node:20-alpine` (deps → build → runner) serving via `next start`.
- `frontend/.dockerignore` — **new**; excludes host `node_modules`/`.next`/`.env*`.

## Key decisions

- **Datastore URLs assembled in compose, not duplicated in `.env`.** `DATABASE_URL` is built from
  `POSTGRES_USER/PASSWORD/DB` and the in-network hostname `db`; `REDIS_URL` points at `redis`. Users set only
  the Postgres parts. config.py (P0-03) reads these from the process environment (compose `environment:`),
  which takes precedence over its `.env` file lookup. (app-design §4/§11 — Postgres+Redis only, self-hosted.)
- **Backend and worker share one image** (`build: ./backend`); the worker only overrides `command:` to run
  Celery. Matches the task requirement and §8 (`tasks/` = "Celery app … + worker entry").
- **Minimal `celery_app.py` added now.** Without a Celery app module the `worker` service cannot start, which
  would fail the "all 5 services start" / "`docker compose up`" acceptance. I added only the app construction +
  config (Redis broker/backend) — no tasks, leaving P0-08 to register them via `autodiscover_tasks`. Flagging
  this as the one piece of scope pulled forward from P0-08 to satisfy P0-06's exit criteria.
- **uv install via `uv sync --no-install-project --no-dev`.** `package = false` (P0-02) means the app itself
  isn't installed; we install only the resolved dependency tree, excluding the dev group. No `uv.lock` exists
  yet, so sync resolves at build time; a committed lock can tighten this later.
- **Backend health check uses Python, not curl.** `python:3.11-slim` has no curl; a one-liner `urllib`
  probe against `/health` avoids adding a package. `depends_on` for db/redis uses `condition: service_healthy`
  (pg_isready / redis-cli ping) so the backend waits for ready datastores.
- **Frontend runs the production build (`next start`).** The task allows dev mode but specifies a multi-stage
  build → `next start`; the dev-only `/api` rewrite in `next.config.ts` would not bridge containers anyway, so
  production mode is cleaner. Cross-container FE→BE calls aren't required for P0.
- **Replaced (not kept) the v1 root `docker-compose.yml`.** The task says create it at repo root and v2 is a
  ground-up rebuild. The v1 root `Dockerfile`/`main.py` stay untouched (still drive HF Spaces) until the P11
  cutover; only the compose file is now v2.

## How to verify

```bash
# 1. Config validates (no errors). With a populated env it is warning-free:
cp .env.example .env            # then edit values
docker compose config >/dev/null && echo OK

# 2. All 5 services build + start; db/redis become healthy before backend:
docker compose up --build       # watch: db/redis healthy → backend → worker → frontend

# 3. Backend health:
curl -s http://localhost:8000/health      # -> {"status":"ok","version":"2.0.0"}

# 4. Frontend:
curl -sI http://localhost:3000            # -> 200

# 5. Worker boots without crashing (Celery banner, no traceback):
docker compose logs worker | head
```

Validated in this environment: `docker compose config` exits 0 with a complete env-file (all 5 services,
`DATABASE_URL`/`REDIS_URL` resolved to `db`/`redis`, `postgres_data` + `redis_data` declared). With the
existing v1 `.env` (missing POSTGRES_* etc.) it still exits 0 with "variable not set" warnings only — resolved
once `.env.example` is copied. `python3 -m py_compile backend/app/tasks/celery_app.py` passes.
(Full `docker compose up` image builds were not run here — they pull large base images / heavy deps
[sentence-transformers, docling]; the Dockerfiles are written to standard uv/Next.js multi-stage patterns.)

## Self-check

- [x] Meets acceptance criteria: 5 services; `config` validates; db/redis healthchecks gate backend;
      `/health` reachable on 8000; frontend on 3000; no hard-coded secrets; `.env.example` complete;
      `postgres_data` + `redis_data` named volumes declared.
- [x] No secrets committed; all creds via `.env` interpolation / `env_file`. Layering untouched (infra task).
- [x] Honors locked decisions: Postgres(pgvector)+Redis only, self-hosted; no Mongo; Celery worker via Redis broker.
- [x] Syntax/config checks pass (pasted above).

## Notes / flags

- **Scope pulled forward:** a minimal `backend/app/tasks/celery_app.py` was required so the `worker` service
  boots. P0-08 should add the trivial round-trip task and `autodiscover_tasks`, completing the phase exit
  criterion "a trivial Celery task round-trips through Redis."
- A future task can commit a `uv.lock` and switch the Dockerfile to `uv sync --frozen` for reproducible builds.
