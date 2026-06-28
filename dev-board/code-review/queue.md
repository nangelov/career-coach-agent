# Review queue

The orchestrator's board. One row per task. See `.claude/skills/agent-handoff/SKILL.md` for the workflow.

- **status:** `ENG` (engineer working) · `REVIEW` (code-reviewer + system-architect running in parallel) · `DONE` · `BLOCKED`
- **rev:** current engineer revision number
- **code-review / arch-review:** `pending` · `APPROVED` · `CHANGES_REQUESTED` (latest verdict of each)

| task-id | title | phase | status | rev | code-review | arch-review |
|---------|-------|-------|--------|-----|-------------|-------------|
| P0-01-backend-skeleton | backend/ directory skeleton | P0 | DONE | 1 | APPROVED | APPROVED |
| P0-02-pyproject-uv | backend/pyproject.toml via uv | P0 | DONE | 1 | APPROVED | APPROVED |
| P0-03-config | app/config.py pydantic-settings | P0 | DONE | 1 | APPROVED | APPROVED |
| P0-04-main-fastapi | FastAPI app factory + /health | P0 | DONE | 1 | APPROVED | APPROVED |
| P0-05-frontend-nextjs | Next.js App Router scaffold | P0 | DONE | 1 | APPROVED | APPROVED |
| P0-06-docker-compose | docker-compose: 5 services | P0 | DONE | 1 | APPROVED | APPROVED |
| P0-07-pgvector | Wire pgvector extension into Postgres | P0 | DONE | 1 | APPROVED | APPROVED |
| P0-08-celery | Celery app + ping task | P0 | DONE | 1 | APPROVED | APPROVED |
| P0-09-backend-ci | Backend CI: ruff + mypy + pytest | P0 | DONE | 1 | APPROVED | APPROVED |
| P0-10-frontend-ci | Frontend CI: eslint + tsc + jest | P0 | DONE | 1 | APPROVED | APPROVED |
| P0-11-verify | P0 exit: all services healthy + checks | P0 | DONE | 1 | APPROVED | APPROVED |
| P0-12-legacy-cleanup | Move v1 code into legacy-code/ | P0 | DONE | 1 | APPROVED | APPROVED |
| P0-13-frontend-rename | Rename frontend-v2/ → frontend/ | P0 | DONE | 1 | APPROVED | APPROVED |
