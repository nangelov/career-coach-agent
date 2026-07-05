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
| P1-01-llm-client | LLMClient interface + HF OpenAI-compatible impl | P1 | DONE | 1 | APPROVED | APPROVED |
| P1-02-llm-router | LLM failover router (timeout/retry/circuit-breaker/resume) | P1 | DONE | 1 | APPROVED | APPROVED |
| P1-03-tools | native tools: current_date_and_time, internet_search | P1 | DONE | 1 | APPROVED | APPROVED |
| P1-04-chat-endpoint | POST /api/chat SSE + model-driven tool-call loop | P1 | DONE | 1 | APPROVED | APPROVED |
| P1-05-session-memory | Redis-backed per-session memory | P1 | DONE | 1 | APPROVED | APPROVED |
| P1-06-cancel-stream | Redis-backed cancel/stop for chat streams | P1 | DONE | 1 | APPROVED | APPROVED |
| P1-07-message-id | Stable message_id on every assistant message | P1 | DONE | 1 | APPROVED | APPROVED |
| P1-08-frontend-chat | Next.js streaming chat page (stop, tool steps) | P1 | DONE | 1 | APPROVED | APPROVED |
| P1-09-verify | P1 exit: chat/tool/stream/stop/failover; no ReAct parser | P1 | DONE | 1 | APPROVED | APPROVED |
| P2-01-repositories | repositories/postgres.py foundation | P2 | DONE | 2 | APPROVED | APPROVED |
| P2-02-alembic | Alembic init + async migration env | P2 | DONE | 1 | APPROVED | APPROVED |
| P2-03-migration-identity | Migration: identity/docs (JSONB) tables | P2 | DONE | 1 | APPROVED | APPROVED |
| P2-04-migration-knowledge | Migration: knowledge/vectors (pgvector) | P2 | DONE | 1 | APPROVED | APPROVED |
| P2-05-migration-structured | Migration: structured (jobs, pdps, dashboard) | P2 | DONE | 1 | APPROVED | APPROVED |
| P2-06-embeddings | llm/embeddings.py + pgvector hybrid search | P2 | DONE | 1 | APPROVED | APPROVED |
| P2-07-persist-conversations | Persist chat to Postgres for logged-in users | P2 | DONE | 2 | APPROVED | APPROVED |
| P2-08-verify | P2 exit: restart-intact history + weighted vector/hybrid search | P2 | DONE | 1 | APPROVED | APPROVED |
| CR-01-design-practices-audit | Whole-codebase design-practices audit (P0-P2) | cross-cutting | DONE | 2 | APPROVED | APPROVED |
| FIX-01-backend-test-deps | Fix failing backend test collection (missing deps) | cross-cutting | DONE | 1 | APPROVED | APPROVED |
| P2-09-integration-verify | Full integration verification against a live container | P2 | DONE | 1 | APPROVED | APPROVED |
| P2-10-ci-postgres-service | Postgres(+pgvector) service container in backend CI | P2 | DONE | 1 | APPROVED | APPROVED |
