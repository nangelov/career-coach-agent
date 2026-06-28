# Code review — P0-06-docker-compose · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | frontend-v2/Dockerfile:29 | `runner` stage copies the full `node_modules` from `builder`, including devDependencies (next/build toolchain). Functional but a bloated production image. | Optional: install prod-only deps in a separate stage (`npm ci --omit=dev`) or adopt Next.js `output: "standalone"` and copy `.next/standalone`. Acceptable for P0 (dev mode allowed); defer. |
| C2 | nit | backend/Dockerfile:24 | `uv sync --no-install-project --no-dev` runs with no committed `uv.lock`, so dependencies resolve at build time (non-reproducible). | Already flagged by engineer; commit a `uv.lock` and switch to `uv sync --frozen` in a later task. |
| C3 | minor | docker-compose.yml:17-18, 32-33 | `db` (5432) and `redis` (6379) are published to the host with no Redis auth and dev Postgres creds. Fine for local dev; would be unsafe if reused as-is beyond localhost. | No change for P0. Note for the P11 deployment task: drop host port publishing for datastores (or bind to 127.0.0.1) and require Redis auth in any non-local environment. |
| C4 | nit | docker-compose.yml:48-49 | `backend`/`worker` get the entire `.env` injected via `env_file` (Postgres + OAuth + SerpAPI vars), more than the backend strictly needs. Harmless — `config.py` uses pydantic-settings default `extra="ignore"`, so unknown env vars are dropped, not rejected. | None required; documenting that the layering is safe. |

## Notes
- Verified `docker compose --env-file .env.example config` exits 0 (all 5 services resolve; `DATABASE_URL`/`REDIS_URL` interpolate to `db`/`redis`; `postgres_data` + `redis_data` named volumes declared). Acceptance criteria for config validation and volumes are met.
- Health gating is correct: `db` (pg_isready) and `redis` (redis-cli ping) use `condition: service_healthy`; backend `depends_on` waits on both. Backend healthcheck uses a `urllib` probe against `/health` (no curl in `python:3.11-slim`) — `urlopen(...).status` is valid on 3.11 and an HTTPError on non-200 propagates to a nonzero exit, i.e. correct "unhealthy" semantics.
- Confirmed `/health` does not crash under the `--no-install-project` image: `app/main.py:33-38` wraps `importlib.metadata.version("career-coach-agent")` in a `PackageNotFoundError` fallback to `"2.0.0"`, so `{"status":"ok","version":"2.0.0"}` is returned even though the project package isn't installed.
- Worker boots: `celery[redis]` is in `pyproject` dependencies; `backend/app/tasks/celery_app.py` exposes a `celery_app` attribute (recognized by `celery -A app.tasks.celery_app`), compiles cleanly, and sources broker/backend from `settings.REDIS_URL` only. Pulling this minimal module forward from P0-08 is the correct minimal scope to satisfy the "all 5 services start" criterion.
- No secrets committed: `.env` is git-ignored (`.gitignore:3`, confirmed via `git check-ignore`); `.env.example` contains only placeholders; both Dockerfiles `.dockerignore` `.env`/`.env*`. The v1 root `Dockerfile`/`main.py` are correctly left untouched per the P11-cutover note.
- Frontend build path is sound: `package-lock.json` present (so `npm ci` works), `.dockerignore` excludes host `node_modules`/`.next`, `public/` exists for the `COPY`, and `next start` runs the copied `.next` build on `PORT=3000`.
- Cross-container FE→BE calls are intentionally out of scope for P0 (the `next.config.ts` `/api` rewrite is dev-only); not gating.
