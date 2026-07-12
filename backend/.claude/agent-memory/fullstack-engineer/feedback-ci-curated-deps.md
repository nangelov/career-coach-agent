---
name: feedback-ci-curated-deps
description: Backend CI installs only light deps (fastapi/pydantic/celery[redis]/openai + dev); heavy ML stack is NOT installed
metadata:
  type: feedback
---

Backend CI (`.github/workflows/backend-ci.yml`) + `backend/Makefile`'s `install`
target do a **curated** install (MUST stay in sync — same list, both places):
`uv sync --only-group dev` + explicit light libs: `fastapi pydantic pydantic-settings
celery[redis] openai sqlalchemy asyncpg aiosqlite pgvector alembic joserfc authlib
langgraph`. It deliberately does NOT `uv sync` the full project, so the genuinely-heavy
ML stack (`torch`/`sentence-transformers`, `langmem`, `docling`) is absent in CI.

**Why:** those ML libs are huge/slow on the free CI tier; lint/type-check/tests
don't exercise them yet. `mypy`'s `ignore_missing_imports=True` keeps un-installed
libs as `Any` so type-check still passes — but **pytest actually executes imports at
collection**, so `ignore_missing_imports` does NOT save a real missing runtime dep:
any module imported at module scope by app.main/app.agents needs its dep curated in.
**How to apply:** (1) A dep declared in `pyproject.toml` is NOT automatically in CI —
if it's imported at module scope and light (no torch/CUDA/ML), add it to BOTH curated
lists. FastAPI file uploads (`UploadFile`/`File`) need **`python-multipart`** — it was
missing from deps AND both curated lists entirely; add it when you add an upload route.
(2) After ANY curated-list change, re-verify **all four tools** (ruff / ruff format /
mypy / pytest) against a fresh curated venv, not just the one reported broken — a bare
`uv run --no-sync pytest` against your full local `.venv` falsely passes past curated
gaps (e.g. docling-dependent tests pass locally, fail in the curated venv). (3) Truly
heavy ML modules must stay behind a lazy/local import. (4) **mypy CI scope is
`app/ migrations/` only — NOT `tests/`** (see Makefile `typecheck` + backend-ci.yml). So
unused-`type: ignore` / arg-type noise in `tests/` (from local-venv stubs that differ
from CI's Any) never gates the pipeline; don't chase those. Keep your OWN test-file
ignores correct anyway, but the authoritative type gate is `mypy app/ migrations/`.
