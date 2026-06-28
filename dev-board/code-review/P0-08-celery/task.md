# Task P0-08-celery — Minimal Celery app in app/tasks/ + ping task to prove broker round-trip

- **Phase:** P0   **Status:** ENG   **Tags:** (B)

## Scope

Wire a minimal Celery application so the `worker` service in docker-compose can start and process tasks:

1. `backend/app/tasks/__init__.py` — exports the Celery `app` instance.
2. `backend/app/tasks/celery_app.py` — creates the Celery app:
   - Broker URL from `settings.redis_url` (e.g. `redis://redis:6379/0`).
   - Result backend from `settings.redis_url` (same Redis, DB 1 or same).
   - `task_serializer = "json"`, `result_serializer = "json"`, `accept_content = ["json"]`.
   - Auto-discovers tasks in `backend.app.tasks.*`.
3. `backend/app/tasks/ping.py` — a single `@celery_app.task(name="tasks.ping")` that returns `{"pong": True}`.
4. `backend/scripts/check_celery.py` — sends `tasks.ping.delay()` and waits for the result (timeout 10 s); prints `Celery OK` and exits 0 on success, exits 1 on timeout/error.
5. Update `backend/app/config.py` if `redis_url` (or equivalent) is not yet present.
6. The `worker` service in `docker-compose.yml` should run:  
   `celery -A backend.app.tasks.celery_app worker --loglevel=info`

## Acceptance criteria

- [ ] `backend/app/tasks/celery_app.py` exists and creates a valid Celery instance.
- [ ] `backend/app/tasks/ping.py` contains the `ping` task.
- [ ] `docker compose up` starts the `worker` service without errors.
- [ ] Running `check_celery.py` (with all services up) prints `Celery OK` and exits 0.
- [ ] Broker URL is sourced from `settings` / env — never hard-coded.
- [ ] No import of the `ping` task at module level in `celery_app.py` (use autodiscovery).

## Design references

- `dev-board/plan.md` — P0 "Minimal Celery app + ping task"
- `dev-board/app-design-and-features.md` — §3 tech stack (Celery + Redis broker), §8 backend structure (`app/tasks/`)
- `backend/app/config.py` — settings (P0-03)
- `docker-compose.yml` — worker service command (P0-06)

## Constraints / non-goals

- No real async jobs yet (OCR, doc-intel, etc.) — that is P5+.
- No Celery Beat / scheduled tasks in this task.
- Result backend persistence tuning is out of scope.
- The check script is a dev utility, not a CI step (CI comes in P0-09).
