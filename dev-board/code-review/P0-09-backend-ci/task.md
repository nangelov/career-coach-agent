# Task P0-09-backend-ci — Backend CI: ruff (lint+format) + mypy + pytest stubs

- **Phase:** P0   **Status:** ENG   **Tags:** (I)

## Scope

Set up a GitHub Actions workflow for the backend that runs on every push/PR:

1. **`.github/workflows/backend-ci.yml`** — workflow with three jobs (or steps):
   - **lint**: `ruff check backend/` and `ruff format --check backend/`
   - **typecheck**: `mypy backend/app/` (strict mode per `pyproject.toml`)
   - **test**: `pytest backend/tests/` (runs the stub suite)

2. **`backend/pyproject.toml`** additions (if not already present):
   - `[tool.ruff]` — `line-length = 100`, `select = ["E","F","I","UP"]`, `ignore = []`
   - `[tool.ruff.format]` — `quote-style = "double"`
   - `[tool.mypy]` — `strict = true`, `python_version = "3.12"`, `ignore_missing_imports = true`
   - `[tool.pytest.ini_options]` — `testpaths = ["backend/tests"]`, `asyncio_mode = "auto"`

3. **`backend/tests/__init__.py`** — empty (marks it as a package).

4. **`backend/tests/test_health.py`** — a stub test using `httpx.AsyncClient` + `ASGITransport` to hit `GET /health` and assert HTTP 200 + `{"status": "ok"}`.

5. Ensure `ruff`, `mypy`, `pytest`, `httpx`, `anyio[trio]` are in `[project.optional-dependencies]` or `[dependency-groups]` in `pyproject.toml`.

## Acceptance criteria

- [ ] `.github/workflows/backend-ci.yml` exists and is valid YAML.
- [ ] `ruff check backend/` passes on the current codebase (fix any violations).
- [ ] `ruff format --check backend/` passes (or files are formatted).
- [ ] `mypy backend/app/` passes with zero errors.
- [ ] `pytest backend/tests/` runs the health stub and passes.
- [ ] CI workflow triggers on `push` and `pull_request` targeting `main` and `version-2` branches.
- [ ] No secrets in the workflow file.

## Design references

- `dev-board/plan.md` — P0 "CI: Backend CI: ruff + mypy + pytest stubs"
- `dev-board/app-design-and-features.md` — §8 backend structure, §3 tech stack (uv, Python 3.12)
- `backend/pyproject.toml` (P0-02) — existing tool config
- `backend/app/main.py` (P0-04) — ASGI app under test

## Constraints / non-goals

- No integration tests against a live DB/Redis (those come in P0-11 verify task).
- No coverage thresholds in this task.
- Frontend CI is a separate task (P0-10).
- Do not run `docker compose` in CI here.
