# Architecture review — P0-08-celery · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Celery app + tasks + worker entry under `backend/app/tasks/` (§8 line 365) | `celery_app.py`, `ping.py`, `__init__.py` all in `backend/app/tasks/`; smoke-test in `backend/scripts/` | none |
| A2 | §3 / §5.3 stack | Celery with **Redis** as broker AND result backend (§3 line 33, §5.3 line 244) | `Celery(... broker=settings.REDIS_URL, backend=settings.REDIS_URL ...)` | none |
| A3 | Datastores locked #9 | Postgres + Redis only, self-hosted; no managed tier | Broker/backend point at the in-network `redis` service (compose `REDIS_URL: redis://redis:6379/0`); no Upstash/managed dependency | none |
| A4 | §5.3 worker process | Separate `worker` process in docker-compose (§5.3 line 244) | compose `worker` service runs `celery -A app.tasks.celery_app worker --loglevel=info`, same image as backend, `depends_on: redis` | none |
| A5 | Config sourcing | Broker URL from settings/env, never hard-coded (acceptance + §6.6 budget/infra) | `settings.REDIS_URL` (Field default + env override, P0-03); compose injects env; check script reads `REDIS_URL` with localhost fallback | none |
| A6 | Phase fit (P0) | Minimal Celery + ping only; no premature OCR/crawl/memory coupling (P5+) | Single trivial `tasks.ping`; future jobs only referenced in docstrings (§5.3), not implemented | none |
| A7 | Connection-pool boundary (§4 line 173) | Celery manages its own Redis connections via kombu, separate from the `repositories/redis.py` shared pool | Celery uses its own broker/backend URLs directly; does not (and should not yet) route through `repositories/redis.py` | none — matches the design's explicit carve-out |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — `tasks/` is infra below Router→Service→Agent/Repo; no DB drivers or service logic leaked in.
- [x] Honors locked decisions — Redis-only broker/backend (#9), self-hosted, no managed tier; no ReAct parser / SSO / embedding concerns in scope here.
- [x] Interfaces-before-implementations — N/A for this infra task; `include`-list discovery keeps future task modules pluggable (just append a module path), no premature engine coupling.
- [x] Budget posture respected — Celery + Redis are OSS/self-hosted; no paid services introduced.

## Notes
- **Package path `app.*` (not `backend.app.*`)** — the engineer correctly followed the established image-root convention (Dockerfile `WORKDIR /app` + `COPY app ./app`, compose `-A app.tasks.celery_app`, `from app.config import settings`) over the literal `backend.app.tasks.*` wording in `task.md`. `backend/` is the build context, so `app` is the runtime import root. Consistent with P0-01…07; no deviation.
- **`include=[...]` vs `autodiscover_tasks(...)`** — architecturally acceptable. The §8 layout uses flat per-concern modules (`ping.py`, future `ocr.py`/`crawl.py`), which does not fit Celery's `tasks.py`-per-package `related_name` convention; `include` of string module paths satisfies the "no module-level task import / avoid circular import" intent and scales cleanly as §5.3 jobs land. Whether to switch is a code-level call I defer to the code-reviewer; from a design-conformance standpoint it is sound.
- **Result backend DB** — uses the same Redis DB as the broker; `task.md` permitted "DB 1 or same", so compliant. A follow-up to split broker/result onto separate logical DBs is optional and cheap to do later — not a gate.
- No design risk identified for later phases; this is a clean foundation seam for P5+ async work.
