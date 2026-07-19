# Review queue

The orchestrator's board. One row per task. See `.claude/skills/agent-handoff/SKILL.md` for the workflow.

- **status:** `ENG` (engineer working) · `REVIEW` (code-reviewer + system-architect running in parallel) · `DONE` · `BLOCKED`
- **rev:** current engineer revision number
- **code-review / arch-review:** `pending` · `APPROVED` · `CHANGES_REQUESTED` (latest verdict of each)

| task-id | title | phase | status | rev | code-review | arch-review |
|---------|-------|-------|--------|-----|-------------|-------------|
| FIX-12-sso-unconfigured-provider-error | SSO login must fail cleanly when a provider is unconfigured | cross-cutting | DONE | 1 | APPROVED | APPROVED |
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
| P3-01-guest-session | POST /api/auth/guest anonymous session | P3 | DONE | 1 | APPROVED | APPROVED |
| P3-02-sso-oidc | SSO OIDC (Google/LinkedIn) + session JWT + logout | P3 | DONE | 1 | APPROVED | APPROVED |
| P3-03-guest-upgrade | Guest -> account upgrade preserves session | P3 | DONE | 1 | APPROVED | APPROVED |
| P3-04-authz-ratelimits | AuthZ own-data-only + Redis rate limits | P3 | DONE | 1 | APPROVED | APPROVED |
| P3-05-admin-feedback-auth | Replace v1 get-feedback token auth with real admin auth | P3 | DONE | 1 | APPROVED | APPROVED |
| P3-06-login-ui | Login UI (Google/LinkedIn/guest) + bearer session handling | P3 | DONE | 1 | APPROVED | APPROVED |
| P3-07-verify | P3 exit: guest/SSO/upgrade/cross-user-denied | P3 | DONE | 1 | APPROVED | APPROVED |
| P4-01-agent-state | agents/state.py typed shared LangGraph state | P4 | DONE | 1 | APPROVED | APPROVED |
| P4-02-agent-graph | agents/graph.py LangGraph wiring | P4 | DONE | 1 | APPROVED | APPROVED |
| P4-03-planner | agents/planner.py intent classify/decompose/route/budget | P4 | DONE | 2 | APPROVED | APPROVED |
| P4-04-rag-agent | agents/rag_agent.py embed/retrieve/cite | P4 | DONE | 1 | APPROVED | APPROVED |
| P4-05-web-searcher | agents/web_searcher.py search + bounded crawl | P4 | DONE | 1 | APPROVED | APPROVED |
| P4-06-responder | agents/responder.py synthesize/cite/format/stream | P4 | DONE | 1 | APPROVED | APPROVED |
| P4-07-chat-graph-integration | Wire multi-agent graph into POST /api/chat | P4 | DONE | 1 | APPROVED | APPROVED |
| P4-08-input-guardrails-minimal | Minimal input guardrails wired + routed | P4 | DONE | 1 | APPROVED | APPROVED |
| P4-09-frontend-plan-citations | Stream planner/worker steps + citations to UI | P4 | DONE | 2 | APPROVED | APPROVED |
| P4-10-verify | P4 exit: routing/streaming/citations/guardrail/regression | P4 | DONE | 1 | APPROVED | APPROVED |
| FIX-02-mypy-ci-curated-deps | Fix mypy failing in CI's curated venv (joserfc + PlannerNode alias) | cross-cutting | DONE | 1 | APPROVED | APPROVED |
| FIX-03-pytest-ci-missing-deps | Fix real backend-ci pytest collection failure (authlib + langgraph) | cross-cutting | DONE | 2 | APPROVED | APPROVED |
| P5-01-ingestion-parser | DocumentParser interface + docling primary engine | P5 | DONE | 1 | APPROVED | APPROVED |
| P5-02-ocr-fallback | Type/text-layer detect + OCR fallback (Tesseract/OCRmyPDF) | P5 | DONE | 1 | APPROVED | APPROVED |
| P5-03-profile-structuring | Layout-aware structuring + LLM-assisted structured profile | P5 | DONE | 1 | APPROVED | APPROVED |
| P5-04-cv-upload-endpoint | POST /api/profile/cv Celery task + progress + pgvector embed | P5 | DONE | 2 | APPROVED | APPROVED |
| FIX-04-docling-bytes-import-guard | Guard bytes-source ingestion tests from real docling import in curated CI venv | cross-cutting | DONE | 1 | APPROVED | APPROVED |
| P5-05-profile-crud | GET/PUT /api/profile | P5 | DONE | 1 | APPROVED | APPROVED |
| P5-06-task-status | GET /api/jobs/status/{task_id} | P5 | DONE | 1 | APPROVED | APPROVED |
| P5-07-frontend-cv-upload | CV upload UI + progress + profile view/edit | P5 | DONE | 1 | APPROVED | APPROVED |
| P5-08-verify | P5 exit: scanned PDF + PPTX CV parse async, RAG-grounded | P5 | DONE | 1 | APPROVED | APPROVED |
| FIX-05-docker-frontend-api-routing | Frontend can't reach backend under docker-compose (guest/SSO/chat/profile all 404) | cross-cutting | DONE | 1 | APPROVED | APPROVED |
| SEC-01-ssrf-guard | S1 — SSRF guard for all outbound fetches | SEC | DONE | 2 | APPROVED | APPROVED |
| SEC-02-untrusted-content-contract | S2 — Untrusted-content contract | SEC | DONE | 1 | APPROVED | APPROVED |
| SEC-03-port-lockdown | S5 — Compose port lockdown | SEC | DONE | 1 | APPROVED | APPROVED |
| SEC-04-bff-httponly-cookie | S4 — BFF + httpOnly cookie | SEC | DONE | 2 | APPROVED | APPROVED |
| SEC-05-gdpr-erasure-export | S6 — GDPR erasure + export | SEC | DONE | 2 | APPROVED | APPROVED |
| SEC-06-consent-gate | S13 — Consent gate | SEC | DONE | 1 | APPROVED | APPROVED |
| SEC-07-privacy-tos-pages | Privacy notice + ToS pages | SEC | DONE | 1 | APPROVED | APPROVED |
| SEC-08-contact-redaction | S10 — Contact-detail redaction at LLM egress | SEC | DONE | 1 | APPROVED | APPROVED |
| SEC-09-verify | SEC exit: SSRF/injection/port/cookie/erasure verify | SEC | DONE | 1 | APPROVED | APPROVED |
| SEC-10-container-verify | Live docker-compose + fresh test-suite verification | SEC | DONE | 1 | APPROVED | APPROVED |
| FIX-06-ruff-format-check | Backend CI failing on `ruff format --check` | cross-cutting | DONE | 1 | APPROVED | APPROVED |
| P6-01-taxonomy-seed | ESCO/O*NET taxonomy seed into shared KB | P6 | DONE | 1 | APPROVED | APPROVED |
| P6-02-market-schema | role_profiles + job_postings migration | P6 | DONE | 1 | APPROVED | APPROVED |
| P6-03-tavily-search-provider | Tavily 3-key rotating search pool | P6 | DONE | 1 | APPROVED | APPROVED |
| P6-04-market-agent-and-guardrail | market_agent.py + mining Celery tasks + S3 topic guardrail | P6 | DONE | 2 | APPROVED | APPROVED |
| P6-05-skills-gap | Skills gap: profile vs role_profile | P6 | DONE | 1 | APPROVED | APPROVED |
| P6-06-learning-resource-corpus | Learning-resource corpus crawl (Coursera/Udacity/Udemy/edX) | P6 | DONE | 1 | APPROVED | APPROVED |
| P6-07-roles-api | GET /api/roles/{role}/requirements + /gap | P6 | DONE | 1 | APPROVED | APPROVED |
| P6-08-role-requirements-ui | Role-requirements frontend UI | P6 | DONE | 1 | APPROVED | APPROVED |
| P6-09-manual-verify | P6 exit: cited ranked requirements + gap + cache + redirect | P6 | DONE | 1 | APPROVED | APPROVED |
| FIX-07-market-role-canonicalization-kind-filter | market_agent canonicalization must filter shared KB by meta.kind, not just source_type | cross-cutting | DONE | 1 | APPROVED | APPROVED |
| P6-10-cicd-verify | P6 CI/CD verification | P6 | DONE | 1 | APPROVED | APPROVED |
| FIX-08-frontend-ci-node-deprecation | Bump frontend-ci off deprecated Node 20 actions | cross-cutting | DONE | 1 | APPROVED | APPROVED |
| FIX-09-taxonomy-fixture-gitignored | backend-ci fails: taxonomy_seed.json excluded by over-broad .gitignore | cross-cutting | DONE | 1 | APPROVED | APPROVED |
| P7-01-pdp-agent | agents/pdp_agent.py structured PDP sections | P7 | DONE | 1 | APPROVED | APPROVED |
| P7-02-pdf-builder | pdf/ reportlab builder + validation gate | P7 | DONE | 1 | APPROVED | APPROVED |
| P7-03-pdp-endpoint | POST /api/pdp using stored profile | P7 | DONE | 2 | APPROVED | APPROVED |
| P7-04-frontend-pdp-ui | PDP generation UI (stored profile) + download | P7 | DONE | 1 | APPROVED | APPROVED |
| P7-05-verify | P7 exit: PDP quality vs v1 + header contract | P7 | DONE | 1 | APPROVED | APPROVED |
| P7-06-cicd-verify | P7 CI/CD verification | P7 | DONE | 1 | APPROVED | APPROVED |
| FIX-11-backend-ci-reportlab-missing | backend-ci pytest collection fails: reportlab uncurated | cross-cutting | DONE | 1 | APPROVED | APPROVED |
| P8-01-dashboard-schema-confirm | Confirm goals/milestones/tasks/progress_entries tables | P8 | DONE | 1 | APPROVED | APPROVED |
| P8-02-dashboard-api | api/dashboard.py CRUD + summary endpoint | P8 | DONE | 1 | APPROVED | APPROVED |
| P8-03-dashboard-tools | Native dashboard tools (read + propose) in chat graph | P8 | DONE | 2 | APPROVED | APPROVED |
| FIX-10-p8-ruff-format-debt | Reformat P8-01/P8-02 files flagged by ruff format --check | cross-cutting | DONE | 1 | APPROVED | APPROVED |
| P8-04-pdp-seed-dashboard | PDP generation seeds goals/tasks into the dashboard | P8 | DONE | 1 | APPROVED | APPROVED |
| P8-05-dashboard-ui | Dashboard frontend UI | P8 | DONE | 1 | APPROVED | APPROVED |
| P8-06-verify | P8 exit: edit/propose/approve/progress | P8 | DONE | 1 | APPROVED | APPROVED |
| P8-07-cicd-verify | P8 CI/CD verification | P8 | DONE | 1 | APPROVED | APPROVED |
| P8-08-curated-deps-guard | Guard against curated-CI-dependency drift | P8 | DONE | 1 | APPROVED | APPROVED |
| P9-01-message-feedback | message_feedback capture (👍/👎 + reason) | P9 | DONE | 1 | APPROVED | APPROVED |
| P9-02-langmem-recall | LangMem recall wired before the planner | P9 | DONE | 1 | APPROVED | APPROVED |
| P9-03-langmem-learn-task | Post-turn learn step (Celery, extract/dedup/confidence/demote) | P9 | DONE | 2 | APPROVED | APPROVED |
| P9-04-memory-pii-gdpr-filter | S7: PII redaction + GDPR Art. 9 exclusion before memory writes | P9 | DONE | 1 | APPROVED | APPROVED |
| P9-05-memory-crud-api | Memory panel API (silent-but-viewable/deletable) | P9 | DONE | 1 | APPROVED | APPROVED |
| P9-06-responder-tone-adaptation | Responder adapts to recalled preferences/memories | P9 | DONE | 1 | APPROVED | APPROVED |
| P9-07-guest-personalization-redis | Guest personalization session-only (Redis); upgrade persists | P9 | DONE | 1 | APPROVED | APPROVED |
| P9-08-retention-purge | S14: periodic retention purge (30 days after last activity) | P9 | DONE | 1 | APPROVED | APPROVED |
| P9-09-frontend-feedback-memory-panel | 👍/👎 + try again + memory panel (frontend) | P9 | DONE | 1 | APPROVED | APPROVED |
| P9-10-verify | P9 exit: cross-session adaptation; 👎 changes behavior; inspect/delete | P9 | DONE | 1 | APPROVED | APPROVED |
| P9-11-cicd-verify | P9 CI/CD verification | P9 | DONE | 1 | APPROVED | APPROVED |
