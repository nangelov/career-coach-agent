# Engineer report — P0-08-celery · Revision 1

## Summary
Fleshed out the minimal Celery application so the docker-compose `worker` service can boot and
process tasks. Added a `tasks.ping` task that proves the broker → worker → result-backend
round-trip, plus a self-contained `check_celery.py` dev smoke-test that enqueues it and waits for
the result. Broker/result-backend URLs come from `settings.REDIS_URL` (env-sourced), never
hard-coded.

## Files changed
- `backend/app/tasks/celery_app.py` — replaced the stub: constructs the `celery_app` instance wired
  to `settings.REDIS_URL` for both broker and result backend; sets json serializers + UTC; declares
  `include=["app.tasks.ping"]` for lazy task-module loading (no eager task import here).
- `backend/app/tasks/ping.py` — **new**: `@celery_app.task(name="tasks.ping")` returning
  `{"pong": True}`.
- `backend/app/tasks/__init__.py` — re-exports the Celery instance as `app` (`from
  app.tasks.celery_app import celery_app as app`).
- `backend/scripts/check_celery.py` — **new**: dependency-light smoke-test mirroring
  `check_pgvector.py`; dispatches `tasks.ping` by name and waits (10 s); prints `Celery OK` / exit 0
  on success, exit 1 on timeout/error/unexpected result.

No changes needed to `backend/app/config.py` (`REDIS_URL` already present, P0-03) or
`docker-compose.yml` (the `worker` service already runs
`celery -A app.tasks.celery_app worker --loglevel=info`, P0-06).

## Key decisions
- **Package path is `app.*`, not `backend.app.*`.** The task text says `backend.app.tasks.*`, but the
  established (and already-approved P0-01…07) convention is the `app` package at the image root
  (Dockerfile `WORKDIR /app` + `COPY app ./app`; `celery_app.py` imports `from app.config import
  settings`; the compose worker uses `-A app.tasks.celery_app`). I followed `app.*` for consistency.
- **Task discovery via `include=[...]` rather than `autodiscover_tasks(...)`.** The acceptance
  criterion's intent is "no module-level import of the ping task in `celery_app.py`" (each task module
  imports `celery_app` back, so importing them here would be circular). Celery's `autodiscover_tasks`
  follows a `tasks.py`-per-package related-name convention that does **not** match our flat
  `ping.py` filename, so it would silently fail to register the task. `include` is the standard,
  scalable mechanism for a flat module layout: it passes **string module paths** (no eager task
  import, no circular import) that the worker imports at startup to register every `@celery_app.task`.
  Future modules (OCR/crawl/memory — §5.3) just append their path. **Flagging for reviewer:** if you
  prefer the literal `autodiscover_tasks`, it would require `related_name="ping"` (couples to the
  filename) or a `tasks.py` rename — happy to switch.
- **Check script is self-contained and does NOT import `app.config`.** Mirrors `check_pgvector.py`:
  importing `settings` would force unrelated required secrets (HF_API_TOKEN, DATABASE_URL,
  JWT_SECRET_KEY) to be set just to ping Redis. It builds a throwaway `Celery(broker, backend)` from
  `REDIS_URL` and uses `send_task("tasks.ping")` (the by-name equivalent of `ping.delay()`), so it
  needs neither settings nor the task object.
- **Exit codes:** `0` + `Celery OK` on success; `1` on any timeout/connection error/unexpected
  result, per the task ("exits 1 on timeout/error").

## How to verify
Requires the stack running (broker + a worker):
```bash
cp .env.example .env   # fill required secrets if not already done
docker compose up --build        # starts db, redis, backend, worker, frontend
# worker logs should show: celery@... ready. + task "tasks.ping" registered

# From the repo root, against the running stack:
python backend/scripts/check_celery.py    # -> "Celery OK", exit 0
echo $?                                    # -> 0
```
Static checks already run:
```bash
python3 -m py_compile backend/app/tasks/celery_app.py backend/app/tasks/ping.py \
  backend/app/tasks/__init__.py backend/scripts/check_celery.py   # -> PY_COMPILE OK
```

## Self-check
- [x] Meets acceptance criteria — `celery_app.py` builds a valid instance; `ping.py` has the
  `tasks.ping` task; compose `worker` command already correct; `check_celery.py` prints `Celery OK` /
  exit 0; broker URL from `settings.REDIS_URL`; no module-level import of the ping task in
  `celery_app.py`.
- [x] No secrets committed; broker/backend URLs sourced from env via `settings.REDIS_URL`. Layering
  respected — this is infra (tasks/) below the Router→Service→Agent/Repo flow; no DB drivers touched.
- [x] Tests/lints pass (paste result): `python3 -m py_compile ... -> PY_COMPILE OK`. ruff/pytest not
  installed in this WSL system Python (project deps live in the uv venv / image); per project memory,
  `py_compile` is the syntax gate for skeleton/stub tasks. No unit tests in scope (dev utility, CI is
  P0-09).

## Response to review (revisions only)
- N/A (revision 1).
