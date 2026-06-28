# Code review — P0-09-backend-ci · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | `.github/workflows/backend-ci.yml:51-54` | Curated install hand-lists runtime libs (`fastapi pydantic pydantic-settings celery[redis]`). This silently breaks the moment a module under `app/` (checked by mypy) or `tests/` (run by pytest) imports an uncurated lib (e.g. `sqlalchemy`, `redis`, `asyncpg`, `openai`). Verified sufficient for the *current* import set only. | No change now (documented as a revisit point). When P1+ adds imports, split deps into an extra (e.g. `[project.optional-dependencies] ml`) or widen the install so CI fails loudly rather than from a missing top-level import. |
| C2 | nit | `backend/pyproject.toml` (no `uv.lock`) | No lockfile committed, so each CI run resolves latest-compatible ruff/mypy/pytest. A future tool release can turn CI red with no code change. Engineer verified floor (ruff 0.3.0 / mypy 1.8.0) and latest pass today. | Optional follow-up: commit `uv.lock` (or pin tool versions) for reproducible CI. |
| C3 | nit | `backend/scripts/*.py` | `scripts/check_pgvector.py` / `check_celery.py` are linted by `ruff check .` but not type-checked (`mypy app/` per task spec) and import `asyncpg`/`celery` not all of which are in the CI venv (no import = OK for ruff). | None required — matches task spec (`mypy backend/app/`). Note only: dev scripts are outside the type gate. |

## Notes
- Ran the engineer's full verify sequence in a fresh curated venv (Python 3.11.15): `ruff check .` → All checks passed; `ruff format --check .` → 22 files already formatted; `mypy app/` → Success, no issues in 17 files; `pytest` → 1 passed. YAML parses (`jobs: [backend]`, triggers `push`/`pull_request`). All acceptance criteria met.
- Security posture is good: `permissions: contents: read` (least privilege), uses `pull_request` (not the dangerous `pull_request_target`), no `secrets.*` references, and the only `${{ }}` interpolation is `github.ref` inside a `concurrency.group` (not shell-evaluated — no injection surface). `conftest.py` seeds non-secret dummy env via `setdefault` before app import — hermetic, no real credentials.
- `mypy --strict` passes including `request: Request[Any]` in `RequestIDMiddleware.dispatch` — confirmed valid under the installed Starlette (Request is generic there); runtime is unaffected regardless thanks to `from __future__ import annotations`.
- Documented task deviations (mypy `python_version=3.11` vs suggested 3.12; `testpaths=["tests"]` vs `["backend/tests"]`; `working-directory: backend` vs repo-root-prefixed paths) are all correct given `requires-python>=3.11`, the `python:3.11-slim` Dockerfile, and pytest rootdir semantics. `["backend/tests"]` would have wrongly resolved to `backend/backend/tests`; the engineer's choice is the right one.
- `concurrency` with `cancel-in-progress` and `paths` filters are sensible CI hygiene. One downstream caveat (not a defect): `paths`-filtered `pull_request` runs are reported as skipped, which can complicate branch-protection required-check config later.
- Touched files `app/main.py` (middleware typing) and `scripts/check_pgvector.py` (reformat) are typing/format-only with no behavior change — confirmed by reading the diff.

## Verdict: APPROVED
