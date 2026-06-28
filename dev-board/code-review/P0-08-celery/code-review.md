# Code review — P0-08-celery · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/app/tasks/celery_app.py:33 | Acceptance criterion #6 literally says "use autodiscovery", but task discovery is done via `include=["app.tasks.ping"]` rather than `celery_app.autodiscover_tasks(...)`. | None required. `include` (string module paths imported by the worker at startup) satisfies the *intent* of the criterion — no module-level import of the `ping` task object in `celery_app.py`, hence no circular import — and is the correct mechanism for the flat `ping.py` layout (`autodiscover_tasks` follows a `tasks.py`-per-package related-name convention that would silently fail to register `tasks.ping`). Engineer flagged this explicitly; documented and accepted. |
| C2 | nit | backend/app/tasks/celery_app.py:28-29 | Broker and result backend share the same Redis logical DB (`redis://redis:6379/0`) rather than separating onto DB 1. | None required. Task text permits "DB 1 or same"; Celery stores results under `celery-task-meta-*` keys that do not collide with broker queue keys. Fine for P0; revisit only if result/broker isolation becomes desirable. |

## Notes
- **Correctness of the round-trip — verified by tracing the code paths:**
  - Worker boot: `-A app.tasks.celery_app` resolves the instance even though it is named `celery_app` (not the conventional `app`/`celery`). Celery's `find_app` imports the module, fails the `sym.app`/`sym.celery` lookups, then scans the module's globals for any `Celery` instance and returns `celery_app`. Only one instance exists in that module's namespace (`from celery import Celery` is the class, not an instance), so resolution is unambiguous. This wiring matches the worker command already in `docker-compose.yml` (P0-06, approved).
  - No circular import: the worker creates `celery_app` first (via `-A`), then lazily imports the `include` modules; `ping.py`'s `from app.tasks.celery_app import celery_app` hits the already-cached module. `celery_app.py` never imports the task object.
  - Result serialization round-trip is consistent: worker sets `result_serializer="json"` + `accept_content=["json"]`; `check_celery.py`'s throwaway client sets the matching `accept_content`/serializers, so `async_result.get()` can deserialize `{"pong": True}`.
- **`check_celery.py` is correct and robust:** self-contained (no `app.config` import, avoiding unrelated required secrets — mirrors `check_pgvector.py`), `_REPO_ROOT = parents[2]` correctly points at the repo root from `backend/scripts/`, existing env values are never overwritten by the `.env` loader, 10 s timeout, and exit codes are `0`+`Celery OK` on the expected payload / `1` on timeout/connection error/unexpected result. The broad `except Exception` is appropriately scoped for a dev smoke-test (annotated with `noqa`).
- **Security:** no secrets hard-coded; broker/backend URLs sourced from `settings.REDIS_URL` / `REDIS_URL` env. No untrusted input reaches the task; the `ping` task is a pure constant return. No arbitrary-execution surface.
- **Acceptance criteria:** all met — `celery_app.py` builds a valid instance; `ping.py` defines `tasks.ping`; compose `worker` command is correct; `check_celery.py` prints `Celery OK`/exit 0 on success; broker URL from settings; no module-level import of the ping task in `celery_app.py`.
- `py_compile` passes on all four files. Package-path choice (`app.*` vs the task's `backend.app.*`) matches the established P0-01…07 convention; consistency call left to the system-architect's lane.
