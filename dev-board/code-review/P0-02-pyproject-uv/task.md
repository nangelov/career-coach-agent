# Task P0-02-pyproject-uv — backend/pyproject.toml via uv

- **Phase:** P0   **Status:** ENG   **Tags:** (I)

## Scope

Replace/complete the stub `backend/pyproject.toml` created in P0-01 with a fully working **uv**-managed
`pyproject.toml` that captures all known v2 backend dependencies. This replaces the old root-level
`requirements.txt` as the single source of truth for Python dependencies.

Specifically:
- Fill in `[project]` metadata (name, version, requires-python = ">=3.11").
- Add a `[tool.uv]` section and any uv-specific config needed.
- Add the known v2 dependency groups (see constraints below for the full list):
  - Core framework: `fastapi`, `uvicorn[standard]`
  - Settings: `pydantic-settings`, `pydantic`
  - DB / cache: `sqlalchemy`, `alembic`, `asyncpg`, `redis`, `pgvector`
  - Auth: `authlib`, `httpx` (for OIDC flows)
  - LLM / embeddings: `openai` (for HF OpenAI-compatible endpoint), `sentence-transformers`, `langgraph`, `langmem`
  - Background jobs: `celery[redis]`
  - Document ingestion: `docling`, `Pillow`
  - PDF output: `reportlab`
  - Web / search: `serpapi` (or `google-search-results`)
  - Dev/test: `pytest`, `pytest-asyncio`, `httpx` (also test client), `ruff`, `mypy` (in `[dependency-groups]` dev group)
- Add `[tool.ruff]` config: `line-length = 100`, `select = ["E", "F", "I", "UP"]`, `target-version = "py311"`.
- Add `[tool.mypy]` config: `strict = true`, `python_version = "3.11"`.
- Add `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`, `testpaths = ["tests"]`.
- Remove the old root-level `requirements.txt` if it exists (do not leave two dependency files).
- Do **not** run `uv lock` — just write the TOML; locking is done by the engineer in their dev environment
  and is outside the scope of this skeleton task.

## Acceptance criteria

- [ ] `backend/pyproject.toml` is valid TOML and contains `[project]`, `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]` sections
- [ ] All known v2 backend dependencies are listed (see scope above)
- [ ] Dev dependencies are in a `[dependency-groups]` `dev` group (uv convention)
- [ ] The old root-level `requirements.txt` is either removed or a note is left explaining why it must stay temporarily
- [ ] `python -c "import tomllib; tomllib.load(open('backend/pyproject.toml','rb'))"` passes (valid TOML)

## Design references

- `dev-board/app-design-and-features.md`: §2 Tech Stack, §8 Target Project Structure
- `dev-board/plan.md`: Phase 0

## Constraints / non-goals

- Use **uv** conventions (`[dependency-groups]` for dev deps, not `[project.optional-dependencies]`)
- Do NOT pin exact versions — use minimum bounds (`>=`) or leave unpinned for flexibility
- Do NOT delete or rename any of the sub-package `__init__.py` files from P0-01
- Do NOT implement any Python logic — this task is purely `pyproject.toml` + tooling config
- The `backend/Dockerfile` stub is out of scope for this task
