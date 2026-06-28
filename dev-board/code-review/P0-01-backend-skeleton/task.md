# Task P0-01-backend-skeleton — Create backend/ directory skeleton

- **Phase:** P0   **Status:** ENG   **Tags:** (I)

## Scope

Create the `backend/` directory skeleton per design §8 of `dev-board/app-design-and-features.md`. This means:

- Create `backend/app/` with the following empty sub-packages (each with an `__init__.py`):
  - `api/`
  - `agents/`
  - `llm/`
  - `tools/`
  - `ingestion/`
  - `memory/`
  - `tasks/`
  - `guardrails/`
  - `services/`
  - `repositories/`
  - `pdf/`
  - `schemas/`
- Create `backend/migrations/` (empty dir, with a `.gitkeep`)
- Create `backend/tests/` with an `__init__.py`
- Place a stub `backend/app/__init__.py`
- Place a stub `backend/app/main.py` (empty FastAPI app factory — just `from fastapi import FastAPI; app = FastAPI()` so the module is importable)
- Place a stub `backend/app/config.py` (empty module with a comment: `# pydantic-settings config — implemented in P0-03-config`)
- Place a stub `backend/pyproject.toml` (minimal — just `[project]` with name + python-requires; dependencies left empty — filled in a later P0 task)
- Place a stub `backend/Dockerfile` (single comment: `# Backend Dockerfile — filled in P0 infra task`)

Do **not** implement any real logic. This is a skeleton only — empty packages + stub files. The goal is that the directory tree matches §8 so all subsequent tasks can import from the right places.

## Acceptance criteria

- [ ] `backend/app/` exists and contains all 12 sub-packages listed above, each with an `__init__.py`
- [ ] `backend/app/main.py` is importable (`python -c "from backend.app.main import app"` succeeds — or at minimum the file exists and is syntactically valid Python)
- [ ] `backend/migrations/` and `backend/tests/` exist
- [ ] `backend/pyproject.toml` exists and is valid TOML
- [ ] No real business logic is added — stubs only

## Design references

- `dev-board/app-design-and-features.md`: §8 "Target Project Structure"
- `dev-board/plan.md`: "Phase 0 — Decisions & Scaffolding"

## Constraints / non-goals

- Do NOT implement `config.py` with pydantic-settings (that is P0-03-config)
- Do NOT write the docker-compose.yml (separate P0 task)
- Do NOT scaffold the Next.js frontend (separate P0 task)
- Do NOT add any dependencies beyond what's needed for the stub to be importable
- Keep every stub file minimal — a comment or a single import is enough
