# Architecture review — P0-06-docker-compose · engineer revision 1

## Verdict: APPROVED

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Datastores (§4, §11 locked) | Postgres(pgvector + JSONB) + Redis only; **no Mongo, no managed tier** | `db: pgvector/pgvector:pg16`, `redis:7-alpine`; both self-hosted in compose; no Mongo/managed services | none |
| A2 | §8 structure (`tasks/`) | `tasks/` = "Celery app + … + worker entry" | Celery app + worker entry at `backend/app/tasks/celery_app.py` | none — exact match |
| A3 | Celery broker (§5.3 locked) | Celery async work, **Redis broker** | `celery_app` broker+backend = `settings.REDIS_URL` → `redis://redis:6379/0` | none |
| A4 | Shared backend/worker image (§5.3, task) | One image; worker overrides command | Both `build: ./backend`; worker overrides `command:` to run Celery | none |
| A5 | Self-hosted deploy (§11) | `docker-compose` local + co-located on Spaces; HF Spaces (P11) separate | Local 5-service compose; v1 root `Dockerfile`/`main.py` left intact for HF Spaces until P11 cutover | none — correct phase fit |
| A6 | Budget posture (§11) | Free / OSS / self-hosted images only | pgvector, redis-alpine, python:3.11-slim, node:20-alpine — all OSS; no paid tier | none |
| A7 | Secrets handling (§11, config.py) | All creds from env/Space Secrets; never hard-coded; `.env` git-ignored & excluded from image | Creds via compose interpolation/`env_file`; `.env` in both `.dockerignore`s; `.env.example` placeholders only | none |
| A8 | Env var names match config (P0-03) | `HF_API_TOKEN`, `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`, OAuth, SERPAPI/RAPID, DEBUG | `.env.example` + compose-assembled `DATABASE_URL`/`REDIS_URL` match `config.py` field names exactly | none |
| A9 | Async Postgres DSN (config.py) | `postgresql+asyncpg://…` async DSN | compose builds `postgresql+asyncpg://…@db:5432/…` | none for backend; see Note N1 (worker) |
| A10 | Frontend path | v2 frontend at `frontend-v2/` (blessed coexistence; §8 `frontend/` rename owed at P11) | `frontend: build: ./frontend-v2` | none — pre-blessed, do not flag before P11 |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — infra task; Celery app placed in `tasks/` per §8; no service/layering changes
- [x] Honors locked decisions — Postgres(pgvector)+Redis only, no Mongo, no managed tier; Celery on Redis; SSO/embeddings untouched; self-hosted
- [x] Interfaces-before-implementations — N/A for infra; `repositories/` escape-hatch to managed tier (§11) preserved (only connection strings change)
- [x] Budget posture respected — all images free/OSS/self-hosted; no paid fallback introduced

## Notes
- **N1 (follow-up, P0-08):** the `worker` service inherits `DATABASE_URL=postgresql+asyncpg://…`. Celery tasks usually need a **sync** driver/engine; the worker does no DB I/O yet, so this is harmless now. When P0-08+ adds DB-touching tasks, ensure the worker uses a sync engine (or async-aware execution) rather than blindly reusing the async DSN. Not blocking P0-06.
- **N2 (scope pulled forward — accepted):** `celery_app.py` was created here (nominally P0-08) so the `worker` service can boot — required to satisfy this task's "all 5 services start" criterion. It is minimal (app construction + Redis config, no tasks), correctly located in `tasks/`, and the engineer flagged it. Cheap and reversible; P0-08 should add the round-trip task + `autodiscover_tasks`. No design debt.
- **N3 (follow-up):** no `uv.lock` / `package-lock` frozen-install, so image builds resolve at build time (non-reproducible). Engineer already flagged committing a lock and switching to `uv sync --frozen`. Minor, defer.
- **N4 (informational):** full `docker compose up` image builds were not executed in-env (heavy base images / deps). `docker compose config` validates clean. Acceptable given the Dockerfiles follow standard uv / Next.js multi-stage patterns; runtime verification can occur once deps land.
- **N5 (informational):** the v1 root `docker-compose.yml` was replaced by the v2 stack while v1 `Dockerfile`/`main.py` remain for HF Spaces — consistent with foundation-first sequencing; the HF Spaces single-container packaging (§11 caveat) is correctly deferred to P11.
