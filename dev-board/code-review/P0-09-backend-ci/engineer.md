# Engineer report — P0-09-backend-ci · Revision 1

## Summary
Added a backend GitHub Actions workflow that lints (ruff), type-checks (mypy
`--strict`), and runs the pytest stub suite on every push/PR to `main` and
`version-2`. Extended `backend/pyproject.toml` with the ruff-format, mypy-plugin,
and dev-dependency config needed for the checks to pass, added a `httpx`-based
`GET /health` stub test plus a hermetic test env bootstrap, and fixed the few
strict-mode typing/format violations the new gate surfaced in existing P0-04/P0-08
code.

All four checks pass locally against **both** the dependency floors
(ruff 0.3.0 / mypy 1.8.0) and the latest releases (ruff 0.15.20 / mypy 2.1.0),
so the unpinned CI install is resilient.

## Files changed
- `.github/workflows/backend-ci.yml` — new workflow; single `backend` job with
  steps: checkout → setup-uv (cache) → install Python 3.11 → curated dependency
  install → ruff check → ruff format --check → mypy → pytest. Triggers on
  push/PR to `main`/`version-2`, path-filtered to `backend/**` + the workflow file.
- `backend/pyproject.toml` — added `[tool.ruff.format] quote-style = "double"`;
  added to `[tool.mypy]`: `ignore_missing_imports = true` and
  `plugins = ["pydantic.mypy"]`; added `anyio[trio]` and `celery-types` to the
  `dev` dependency group. (`line-length`, ruff `select`, `strict`, `asyncio_mode`,
  `testpaths` were already present from P0-02.)
- `backend/tests/test_health.py` — new; async stub hitting `GET /health` via
  `httpx.AsyncClient` + `ASGITransport`, asserts 200 and body `status == "ok"`.
- `backend/tests/conftest.py` — new; seeds dummy values for the three required
  settings (`HF_API_TOKEN`, `DATABASE_URL`, `JWT_SECRET_KEY`) via
  `os.environ.setdefault` before app import, so the suite is hermetic and needs no
  real secrets or live DB. Non-secret placeholders only.
- `backend/app/main.py` — typed `RequestIDMiddleware.dispatch`
  (`request: Request[Any]`, `call_next: RequestResponseEndpoint`, `-> Response`)
  and dropped the now-unused `# type: ignore[override]`; added the needed imports.
  Required to pass `mypy --strict`.
- `backend/scripts/check_pgvector.py` — reformatted by `ruff format` (one
  over-wrapped call collapsed onto a sub-100-char line). No behavior change.

## Key decisions
- **Curated install instead of full `uv sync`.** `backend`'s runtime deps include
  the heavy ML stack (torch + full CUDA wheels, docling, sentence-transformers ≈
  3 GB / 150 packages) which lint/type-check/the health test never exercise. The
  workflow installs only `uv sync --only-group dev` plus the light runtime libs the
  app currently imports (`fastapi pydantic pydantic-settings celery[redis]` → 52
  packages, no torch). Keeps CI fast and within the free/OSS budget posture
  (design §2 / locked decisions). Documented inline as a revisit point: when P1+
  tests import ML modules, split deps into an extra (e.g. `[project.optional-
  dependencies] ml`) or widen the install.
- **`uv run --no-sync` for the check steps.** Plain `uv run` auto-resolves and
  installs the *entire* project before running, which would re-introduce the heavy
  stack despite the curated install. `--no-sync` runs each tool in the
  already-prepared venv.
- **`working-directory: backend`.** Run from `backend/` so ruff/mypy/pytest
  discover `backend/pyproject.toml` for config (the task's repo-root command forms
  `ruff check backend/` etc. don't pick up the nested config for mypy/pytest). The
  effective commands (`ruff check .`, `mypy app/`, `pytest`) are semantically
  equivalent to the task's spec.
- **mypy `python_version` kept at 3.11 (task suggested 3.12).** `requires-python =
  ">=3.11"` and the Dockerfile use `python:3.11-slim`; aligning the type-checker
  with the actual runtime floor is safer than 3.12. Flagging the deviation per the
  task text.
- **`testpaths = ["tests"]` kept (task suggested `["backend/tests"]`).** `testpaths`
  is relative to the rootdir (`backend/`), so `["tests"]` is correct;
  `["backend/tests"]` would resolve to `backend/backend/tests`.
- **`plugins = ["pydantic.mypy"]` + `celery-types`.** Strict mypy otherwise flags
  `Settings()` as missing required args (pydantic-settings reads them from env) and
  the `@celery_app.task` decorators as untyped (celery ships no `py.typed`). The
  pydantic plugin and the celery stub package resolve both without per-module
  strictness opt-outs.
- **`conftest.py` env bootstrap.** `app.config.Settings` fails fast on missing
  required secrets at import time; seeding dummy env keeps the unit suite hermetic
  (non-goal: no live DB/Redis).

## How to verify
From `backend/` (mirrors the CI steps):
```bash
uv sync --only-group dev
uv pip install fastapi pydantic pydantic-settings "celery[redis]"
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy app/
uv run --no-sync pytest
```
Workflow YAML validity:
```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/backend-ci.yml'))"
```

Results (this revision):
- `ruff check .` → `All checks passed!`
- `ruff format --check .` → `22 files already formatted`
- `mypy app/` → `Success: no issues found in 17 source files`
- `pytest` → `1 passed`
- YAML parse → valid
Verified with both floor (ruff 0.3.0 / mypy 1.8.0) and latest (ruff 0.15.20 /
mypy 2.1.0) tool versions.

## Self-check
- [x] Meets acceptance criteria (workflow valid YAML; ruff check + format pass;
      mypy strict 0 errors; pytest health stub passes; triggers on push/PR to
      `main` + `version-2`; no secrets in workflow).
- [x] No secrets committed (dummy non-secret env in `conftest.py` only; workflow
      reads no secrets); Router→Service→Agent/Repo layering untouched (CI/test only).
- [x] Tests/lints pass (results pasted above).
- [x] Temporary venvs / ephemeral `uv.lock` removed; nothing extra staged.

## Notes / flags for reviewers
- **Deviation from task spec** (justified above): mypy `python_version` 3.11 not
  3.12; `testpaths` left as `["tests"]`; checks run via `working-directory: backend`
  rather than `backend/`-prefixed paths.
- **No `uv.lock` committed** (consistent with P0-02; `.dockerignore` excludes it),
  so CI resolves latest-compatible tool versions on each run — verified to pass on
  latest. Committing a lock for reproducibility is a possible future task.
- **Curated CI install** will need widening (or a deps split) once P1+ tests import
  ML modules — called out inline in the workflow.
- Touched P0-04 (`main.py`) and P0-08-adjacent (`check_pgvector.py` format) to make
  the new gate green; changes are typing/formatting only, no behavior change.
