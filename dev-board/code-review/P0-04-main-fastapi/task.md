# Task P0-04-main-fastapi — FastAPI app factory + middleware + lifespan + /health

- **Phase:** P0   **Status:** ENG   **Tags:** (B)

## Scope

Create `backend/app/main.py` that:
- Defines a FastAPI application via a `create_app()` factory function.
- Registers middleware: CORS (origins from `settings`), GZip, request-ID header injection.
- Implements an async lifespan context manager (startup: DB pool init stub + Redis ping stub; shutdown: clean close stub).
- Exposes a `GET /health` endpoint returning `{"status": "ok", "version": "<app_version>"}`.
- The module-level `app = create_app()` is the ASGI target (so `uvicorn backend.app.main:app` works).

## Acceptance criteria

- [ ] `GET /health` returns HTTP 200 with `{"status": "ok", "version": ...}`.
- [ ] CORS middleware is wired with origins sourced from `settings` (not hard-coded).
- [ ] Lifespan correctly structures startup/shutdown stubs for DB + Redis (log statements acceptable; real pools come in P2).
- [ ] `create_app()` factory pattern used — the `FastAPI` instance is returned by the function.
- [ ] `uvicorn backend.app.main:app` starts without errors when env vars are set.
- [ ] No secrets or connection strings hard-coded anywhere in the file.
- [ ] Imports `Settings` from `backend.app.config` (already implemented in P0-03).

## Design references

- `dev-board/plan.md` — P0, "Repo layout & tooling" + FastAPI backend
- `dev-board/app-design-and-features.md` — §8 (backend structure), §4 (API layer/router→service layering)
- `backend/app/config.py` — Settings source (P0-03, already done)
- `backend/pyproject.toml` — dependency context (P0-02, already done)

## Constraints / non-goals

- Real DB/Redis connection pools are out of scope (P2). Lifespan stubs only.
- No auth middleware (P3).
- No agent or tool wiring (P4+).
- No route files beyond `/health` in this task.
- Keep it minimal — correct structure is the goal, not feature completeness.
