# Engineer report — P0-01-backend-skeleton · Revision 1

## Summary

Created the `backend/` directory skeleton per design §8. All 12 sub-packages under
`backend/app/` now have `__init__.py` files. The stub `main.py`, `config.py`,
`pyproject.toml`, and `Dockerfile` are in place. No real business logic was added —
all files are stubs or empty packages.

The `backend/` directories already existed in the repo (empty); this task populated
them with the required files only.

## Files changed

- `backend/app/__init__.py` — package init for the top-level app package
- `backend/app/main.py` — stub FastAPI app factory (`from fastapi import FastAPI; app = FastAPI(...)`)
- `backend/app/config.py` — stub with comment pointing to P0-03-config
- `backend/app/api/__init__.py` — empty sub-package init
- `backend/app/agents/__init__.py` — empty sub-package init
- `backend/app/llm/__init__.py` — empty sub-package init
- `backend/app/tools/__init__.py` — empty sub-package init
- `backend/app/ingestion/__init__.py` — empty sub-package init
- `backend/app/memory/__init__.py` — empty sub-package init
- `backend/app/tasks/__init__.py` — empty sub-package init
- `backend/app/guardrails/__init__.py` — empty sub-package init
- `backend/app/services/__init__.py` — empty sub-package init
- `backend/app/repositories/__init__.py` — empty sub-package init
- `backend/app/pdf/__init__.py` — empty sub-package init
- `backend/app/schemas/__init__.py` — empty sub-package init
- `backend/migrations/.gitkeep` — keeps the empty alembic migrations dir in git
- `backend/tests/__init__.py` — empty test package init
- `backend/pyproject.toml` — minimal TOML: `[project]` name + `requires-python = ">=3.11"`, empty `dependencies = []`
- `backend/Dockerfile` — single-comment stub pointing to the P0 infra task

## Key decisions

- **`requires-python = ">=3.11"`** — set in `pyproject.toml` based on the stack
  (LangGraph, asyncio niceties, `tomllib` stdlib all target 3.11+). The design does
  not specify a minimum, but 3.11 is the lowest version with good performance for
  async + type-hint features we will use. Reviewer should flag if a different floor
  is expected.
- **`app = FastAPI(title="Career Coach Agent", version="2.0.0")`** — minimal but
  meaningful stub so the module is importable and the factory pattern is visible from
  day one. No middleware, lifespan, or router registration — those land in P0/P1 tasks.
- **No `[build-system]` section in `pyproject.toml`** — the task says "filled in a
  later P0 task"; `uv` doesn't require it to be present to resolve dependencies, so
  the stub is intentionally minimal. The section will be added when real deps are
  pinned.
- **Comment conventions in `__init__.py` stubs** — each init comment names the
  sub-system and its design section reference, acting as an index for future
  implementors without cluttering the file.

## How to verify

```bash
# From repo root:

# 1. Check all 12 sub-packages + top-level package have __init__.py
find backend/app -name "__init__.py" | sort

# 2. Verify main.py is importable (fastapi must be installed)
python3 -c "from backend.app.main import app; print(app.title)"
# Expected: Career Coach Agent

# 3. Syntax-check all Python stubs
for f in $(find backend -name "*.py" | sort); do
  python3 -m py_compile "$f" && echo "OK: $f"
done

# 4. Validate pyproject.toml is valid TOML
python3 -c "import tomllib; tomllib.loads(open('backend/pyproject.toml').read()); print('TOML OK')"

# 5. Confirm migrations dir and tests dir exist
ls backend/migrations/.gitkeep backend/tests/__init__.py
```

All of the above produced clean output on first run (see self-check below).

## Self-check

- [x] Meets acceptance criteria
  - [x] `backend/app/` contains all 12 sub-packages each with `__init__.py`
  - [x] `backend/app/main.py` is importable (`from backend.app.main import app` succeeds)
  - [x] `backend/migrations/` and `backend/tests/` exist (`.gitkeep` and `__init__.py` respectively)
  - [x] `backend/pyproject.toml` is valid TOML
  - [x] No real business logic added — stubs only
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (N/A for skeleton — no logic exists yet)
- [x] Tests/lints pass

```
=== Syntax check all .py stubs ===
OK: backend/app/__init__.py
OK: backend/app/agents/__init__.py
OK: backend/app/api/__init__.py
OK: backend/app/config.py
OK: backend/app/guardrails/__init__.py
OK: backend/app/ingestion/__init__.py
OK: backend/app/llm/__init__.py
OK: backend/app/main.py
OK: backend/app/memory/__init__.py
OK: backend/app/pdf/__init__.py
OK: backend/app/repositories/__init__.py
OK: backend/app/schemas/__init__.py
OK: backend/app/services/__init__.py
OK: backend/app/tasks/__init__.py
OK: backend/app/tools/__init__.py
OK: backend/tests/__init__.py

=== TOML valid ===
pyproject.toml OK

import OK: Career Coach Agent
```
