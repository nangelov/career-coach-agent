---
name: project-uv-ci-heavy-deps
description: backend runtime deps pull a ~3GB ML/CUDA stack — keep CI installs curated and use `uv run --no-sync`
metadata:
  type: project
---

The v2 `backend` runtime dependencies (sentence-transformers → torch + full CUDA
wheels, docling, transformers) total ~150 packages / ~3 GB. Lint, `mypy --strict`,
and the current pytest stubs never exercise them.

**For CI / lightweight envs:**
- Do **not** `uv sync` the full project just to lint/type/test — install a curated
  set instead: `uv sync --only-group dev` then `uv pip install fastapi pydantic
  pydantic-settings "celery[redis]"` (≈52 packages, no torch). This is what
  `.github/workflows/backend-ci.yml` does.
- **`uv run` auto-syncs the whole project first**, which re-drags in the ML stack.
  Use **`uv run --no-sync`** so the tool runs in the already-prepared venv.

**Why:** keeps CI fast and within the free/OSS budget posture. **How to apply:**
when adding tests that import ML modules, widen the curated install or split deps
into an extra (e.g. `[project.optional-dependencies] ml`) rather than reverting to
a full sync. No `uv.lock` is committed (P0-02 decision; `.dockerignore` excludes
it), so CI resolves latest-compatible versions — verify checks pass on latest tool
releases, not just the floors.
