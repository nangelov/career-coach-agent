# Task P0-06-docker-compose — docker-compose.yml: app + Celery worker + Postgres(pgvector) + Redis

- **Phase:** P0   **Status:** ENG   **Tags:** (I)

## Scope

Create `docker-compose.yml` at the repo root that brings up **5 services**:

| Service | Image / Build | Notes |
|---------|--------------|-------|
| `db` | `pgvector/pgvector:pg16` | Postgres with pgvector pre-installed |
| `redis` | `redis:7-alpine` | Celery broker + session/rate-limit store |
| `backend` | `build: backend/` | FastAPI via uvicorn; depends_on db + redis |
| `worker` | same build as backend | Celery worker; depends_on db + redis |
| `frontend` | `build: frontend/` | Next.js dev server on port 3000 |

Requirements:
- All secrets/credentials come from an `.env` file (never hard-coded); add `.env.example` at root listing every required variable.
- Postgres data persisted via a named volume `postgres_data`.
- Redis data persisted via a named volume `redis_data`.
- Backend exposed on **host port 8000**, frontend on **host port 3000**.
- `backend` and `worker` share the same `Dockerfile` (`backend/Dockerfile`); worker overrides the command to run Celery.
- Health checks on `db` (pg_isready) and `redis` (redis-cli ping); backend's `depends_on` uses `condition: service_healthy`.
- Add `backend/Dockerfile` (production-style: uv install deps → copy source → uvicorn entrypoint).
- Add `frontend/Dockerfile` (multi-stage: node build → serve via `next start`; dev mode is fine for P0).

## Acceptance criteria

- [ ] `docker compose config` validates without errors.
- [ ] `docker compose up` starts all 5 services (db, redis, backend, worker, frontend).
- [ ] `db` and `redis` health checks pass before backend starts.
- [ ] Backend reachable at `http://localhost:8000/health` → `{"status": "ok", ...}`.
- [ ] Frontend reachable at `http://localhost:3000`.
- [ ] No secrets or passwords hard-coded in `docker-compose.yml` or Dockerfiles.
- [ ] `.env.example` lists all required variables with placeholder values.
- [ ] Named volumes `postgres_data` and `redis_data` declared.

## Design references

- `dev-board/plan.md` — P0 "Local infra", P11 "HF Spaces Dockerfile"
- `dev-board/app-design-and-features.md` — §8 (backend structure), §11 (deployment/infra)
- `backend/app/config.py` — env var names (P0-03)
- `backend/app/main.py` — ASGI entrypoint (P0-04)
- `frontend/` — Next.js scaffold (P0-05)

## Constraints / non-goals

- pgvector extension wiring (CREATE EXTENSION) is a separate task (P0-07).
- Celery task implementation is P0-08; worker command just needs to start without crashing.
- No production TLS/reverse-proxy yet (P11).
- No Mongo (locked decision: Postgres+Redis only).
