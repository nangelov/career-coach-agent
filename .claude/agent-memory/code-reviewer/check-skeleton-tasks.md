---
name: check-skeleton-tasks
description: Checklist for reviewing P0 directory-skeleton / scaffold tasks (empty packages + stub files) in this repo
metadata:
  type: project
---

Reviewing a skeleton/scaffold task (e.g. P0-01-backend-skeleton): empty packages + stub files, no logic.

**Why:** these tasks gate on completeness + matching the locked target structure, not on logic — easy to over- or under-scope.

**How to apply — concrete checks:**
- Diff the created package set against the structure block in `dev-board/app-design-and-features.md` §8 ("Target Project Structure"). The authoritative list of `backend/app/` sub-packages lives there. For P0-01 it was exactly 12: api, agents, llm, tools, ingestion, memory, tasks, guardrails, services, repositories, pdf, schemas.
- Run `python3 -m py_compile $(find backend -name "*.py")` to confirm all stubs are syntactically valid.
- Import path gotcha: there is no `backend/__init__.py`, but `backend` still resolves as a PEP 420 **namespace package**, so `python3 -c "from backend.app.main import app"` from repo root (with PYTHONPATH=repo root) DOES import — provided app code uses package-relative imports (`from .config import settings`), which work under both `app.*` and `backend.app.*` prefixes. The documented/intended CWD is still `backend/` (`uvicorn app.main:app`).
- `.env` CWD gotcha: `config.py` uses pydantic-settings `env_file=".env"` (relative to CWD). Running `uvicorn backend.app.main:app` from the repo root picks up the leftover **v1** root `.env` (has `HUGGINGFACEHUB_API_TOKEN`) and crashes with pydantic `extra_forbidden`. So a repo-root invocation can fail even though the import path is fine — distinguish import-resolution failures from config/.env validation failures.
- `__pycache__`/`*.pyc` in the worktree are gitignored (confirmed via `git check-ignore`) — not a finding.
- Validate `pyproject.toml` with `tomllib.loads`.
- Don't gate on design-conformance (package layout vs §8) as a blocker — that's the system-architect's lane; note it briefly. Gate only on correctness/security/quality.
