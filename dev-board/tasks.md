# Career Coach Agent — Development Tasks

> Actionable task breakdown for the v2 rebuild. Derived from [plan.md](./plan.md) (phases P0–P11) and [app-design-and-features.md](./app-design-and-features.md).
> Convention: tasks are grouped by phase; each phase ends in a runnable/demoable state. `[ ]` = todo, `[~]` = in progress, `[x]` = done.
> Tags: **(B)** backend · **(F)** frontend · **(I)** infra/devops · **(D)** decision · **(T)** test/verify.

---

## Pre-work — Decisions to lock before P1

These block downstream work. Resolve and record the choice in CLAUDE.md.

- [x] **(D)** Orchestration → **LangGraph** [DECIDED] (hand-rolled orchestrator rejected).
- [x] **(D)** OSS tool-calling model → **`zai-org/GLM-5.2`** via HF Inference Providers (OpenAI-compatible) [DECIDED]. (Still verify native `tools=[...]` with a throwaway script in P0.)
- [x] **(D)** Embedding model → **`Qwen/Qwen3-Embedding-8B`** in-process via `sentence-transformers`; **vector dimension = 4096** → pgvector `vector(4096)` [DECIDED].
- [x] **(D)** LLM failover → secondary **`Qwen/Qwen3.6-27B`**; **no paid last-resort** [DECIDED].
- [x] **(D)** Guest rate-limit policy → **10 messages + 1 document upload per guest session** [DECIDED] (guests limited harder than logged-in).
- [x] **(D)** Teachable memory → **LangMem** (in-process, over pgvector `user_memories`) [DECIDED] — supersedes the earlier custom-pgvector default.
- [x] **(D)** Mid-stream failover behavior → **resume** (continue the in-flight stream on the secondary model) [DECIDED].
- [x] **(D)** Learned-memory application → **silent-but-viewable/deletable (opt-out)** [DECIDED] — LangMem applies learned facts automatically; user can view & delete via a memory panel (no per-fact confirmation prompts).
- [x] **(D)** Datastores → **self-host only** (Postgres + Redis via `docker-compose` local + co-located on Spaces; **no managed tier** for now) [DECIDED].

---

## P0 — Scaffolding & foundation

**Exit:** `docker compose up` starts FastAPI + Celery worker + Postgres(pgvector) + Redis + Next.js; health check green; trivial Celery task round-trips through Redis.

### Repo layout & tooling
- [x] **(I)** Create `backend/` skeleton per design §8 (`app/`, `api/`, `agents/`, `llm/`, `tools/`, `ingestion/`, `memory/`, `tasks/`, `guardrails/`, `services/`, `repositories/`, `pdf/`, `schemas/`, `migrations/`, `tests/`).
- [x] **(I)** `backend/pyproject.toml` via **uv** (replaces `requirements.txt`).
- [x] **(B)** `app/config.py` with `pydantic-settings`; all secrets via env / Space secrets.
- [x] **(B)** `app/main.py` FastAPI app factory + middleware + lifespan + `/health` endpoint.
- [x] **(F)** Scaffold `frontend/` Next.js (App Router) + TypeScript.

### Local infra
- [x] **(I)** `docker-compose.yml`: app + Celery worker + Postgres(+pgvector) + Redis (Redis = Celery broker). No Mongo.
- [x] **(I)** Wire pgvector extension into the Postgres image/init.
- [x] **(B)** Minimal Celery app in `app/tasks/` + a `ping` task to prove broker round-trip.

### CI
We are using Github free tier.
- [x] **(I)** Backend CI: ruff (lint+format) + mypy + pytest stubs.
- [x] **(I)** Frontend CI: eslint + tsc + test stubs.

### Verify
- [x] **(T)** `docker compose up` brings all 5 services healthy; `/health` green; `ping` Celery task returns through Redis.

### Clean up
- [x] move everything from the legacy v1 under folder `legacy code` to be available as reference, but not used
---

## P1 — Walking skeleton: streaming chat, one agent

**Exit:** user chats, model calls a tool, answer streams token-by-token, stop works, killing the primary model endpoint transparently fails over. **`output_parser.py` is gone.**

- [x] **(B)** `llm/client.py` — `LLMClient` interface + HF OpenAI-compatible implementation; native tool-calling, **no ReAct text parsing**.
- [x] **(B)** `llm/router.py` — failover router (§6.6): ordered models, per-call timeout, retry/backoff for 5xx/429, Redis circuit-breaker + recovery probes.
- [x] **(B)** `tools/` — 1–2 native tools with JSON schemas (`current_date_and_time`, `internet_search`) as the canonical pattern.
- [x] **(B)** `POST /api/chat` — SSE streaming endpoint; model-driven tool-call loop.
- [x] **(B)** Redis-backed per-session memory (replaces global `ConversationBufferMemory`).
- [x] **(B)** Cancel/stop via Redis (`POST /api/chat/{session}/cancel`) — replaces in-process `active_requests` dict.
- [x] **(B)** Stable `message_id` on every assistant message (feedback foundation §5.5).
- [x] **(F)** Next.js chat page: streaming render, stop button, visible tool steps.
- [x] **(T)** Manual: chat → tool call → token stream → stop. Kill primary model → fails over to next.
- [x] **(T)** Confirm no ReAct parser exists in the new backend path.

---

## P2 — Persistence foundation & repositories

**Exit:** chat history survives restart for accounts; vector insert + similarity query verified.

- [x] **(B)** `repositories/postgres.py` (SQLAlchemy/SQLModel + JSONB + pgvector) and `repositories/redis.py` — services never touch drivers directly.
- [x] **(I)** Alembic init + migration env.
- [x] **(B)** Migration: identity/docs (JSONB) — `users`, `profiles`, `preferences`, `sessions`, `conversations`, `messages`, `message_feedback`, `feedback`.
- [x] **(B)** Migration: knowledge/vectors — `kb_documents`, `kb_chunks(embedding vector(4096))`, `user_memories(embedding vector(4096))` (dim fixed by `Qwen/Qwen3-Embedding-8B`).
- [x] **(B)** Migration: structured — `jobs`, `pdps`, dashboard (`goals`, `milestones`, `tasks`, `progress_entries`).
- [x] **(B)** `llm/embeddings.py` — `EmbeddingClient` (in-process `sentence-transformers` `Qwen/Qwen3-Embedding-8B`, 4096-dim) + pgvector write + similarity-search helpers - use Hybrid Search with weights.
- [x] **(B)** Persist P1 conversations to Postgres for **logged-in** users; guests stay Redis-only.
- [x] **(T)** Restart app → account chat history intact. Insert + cosine similarity query on a vector column returns expected neighbor - add extra weighting.
- [x] **(T)** Full integration verification against a live container: `docker compose up -d db` (Postgres+pgvector) → run the full backend test suite so the live-DB-gated integration tests execute instead of skipping (`make test-integration` or equivalent) → confirm green → `docker compose down` to tear the container back down. Repeat this whenever the container/Postgres/pgvector setup or schema changes.
- [x] **(I)** Add a Postgres(+pgvector) service container to backend CI (`.github/workflows/backend-ci.yml`): bring up the service, run migrations, export `DATABASE_URL` so the live-DB-gated integration tests (currently skipped in CI) actually execute on every push/PR instead of only via the local `make test-integration-full` workflow.

---

## P3 — Auth, sessions & guest mode

**Exit:** guest and logged-in flows work; guest→account upgrade carries the session; access control enforced.

- [x] **(B)** `POST /api/auth/guest` → anonymous Redis session (TTL, no history).
- [x] **(B)** SSO via Authlib OIDC (Google + LinkedIn), backend-owned: `GET /api/auth/login/{provider}` + `GET /api/auth/callback/{provider}` with **PKCE**.
- [x] **(B)** Mint short-lived session JWT; FastAPI verify dependency; `POST /api/auth/logout`.
- [x] **(I)** OAuth apps for Google + LinkedIn; client secret + JWT signing key in **HF Space Secrets**; redirect URIs locked to Space domain; minimal scopes (`openid email profile`).
- [x] **(B)** Guest → account upgrade preserves the active session.
- [x] **(B)** AuthZ: users access only their own data; per-session/user rate limits in Redis.
- [x] **(B)** Replace v1 `GET /get-feedback?key=<HF_TOKEN>` with real admin auth.
- [x] **(F)** Login UI (Google/LinkedIn buttons, guest button) + session handling (Bearer token).
- [x] **(T)** Guest flow, SSO flow, upgrade-preserves-session, cross-user access denied.

---

## P4 — Multi-agent orchestration

**Exit:** a query routes planner → ≥1 worker → responder, streams, and cites sources.

- [x] **(B)** `agents/state.py` — typed shared Pydantic state (ids, history slice, planner decisions, worker results, citations, safety verdicts).
- [x] **(B)** `agents/graph.py` — LangGraph wiring (recall → planner → workers → responder → guardrails → memory-writer).
- [x] **(B)** `agents/planner.py` — intent classify, decompose, route to workers, set iteration/token budget.
- [x] **(B)** `agents/rag_agent.py` — embed query, retrieve from pgvector, return grounded snippets + citations.
- [x] **(B)** `agents/web_searcher.py` — search + crawler; crawled content treated as **untrusted data**.
- [x] **(B)** `agents/responder.py` — synthesize, cite, format, stream.
- [x] **(B)** Minimal input guardrails wired here (completed in P10).
- [x] **(F)** Stream planner/worker steps to the UI.
- [x] **(T)** A query routes through planner → ≥1 worker → responder; streams; shows citations.

---

## P5 — Document Intelligence & CV/profile

**Exit:** a scanned/image PDF and a PPTX CV both parse (async, with progress) into a usable structured profile and become RAG-grounded.

- [ ] **(B)** `ingestion/` — `DocumentParser` interface; **docling** as primary engine.
- [ ] **(B)** Type detect + text-layer check; OCR fallback (Tesseract/OCRmyPDF) for scanned/image/slide CVs; reserve VLM-OCR path for hard docs.
- [ ] **(B)** Layout-aware structuring → LLM-assisted parse → structured profile (skills/experience/education/goals).
- [ ] **(B)** `POST /api/profile/cv` runs parsing as a **Celery task** (progress via Redis) → store profile (JSONB) + embed chunks into pgvector.
- [ ] **(B)** `GET/PUT /api/profile`; reuse profile across chats (no re-upload).
- [ ] **(B)** `GET /api/jobs/status/{task_id}` — poll async task progress.
- [ ] **(F)** CV upload UI + progress indicator; profile view/edit.
- [ ] **(T)** Scanned/image PDF and PPTX CV both parse async into a structured profile and are RAG-grounded.

---

## P6 — Richer job search

**Exit:** filtered, deduped, profile-scored results; users can save jobs; repeat queries hit cache.

- [ ] **(B)** `agents/job_agent.py` — multi-source search, normalized listings, dedup into Postgres `jobs`.
- [ ] **(B)** Filters (location/remote/salary) + profile-aware match scoring.
- [ ] **(B)** Crawl + extract structured role profiles (skills/requirements) via web crawler as Celery tasks; crawled = untrusted.
- [ ] **(B)** Save/track jobs per user; cache hot queries in Redis.
- [ ] **(B)** `GET/POST /api/jobs`.
- [ ] **(F)** Job results UI: filters, match score, save/track.
- [ ] **(T)** Filtered + deduped + scored results; save works; repeat query hits cache.

---

## P7 — PDP generator (rebuilt)

**Exit:** PDP PDF matches/exceeds v1 quality, grounded in the user's stored profile.

- [ ] **(B)** `agents/pdp_agent.py` — structured profile + RAG-grounded recommendations → structured PDP sections.
- [ ] **(B)** Port `helpers/helper.py` reportlab builder → `pdf/`; keep section-header contract + `validate_pdp_response` gate.
- [ ] **(B)** `POST /api/pdp` uses the **stored profile** (no re-upload); regenerate on demand.
- [ ] **(F)** PDP generation UI (uses stored profile) + download.
- [ ] **(T)** PDP PDF quality vs v1; section headers stay in sync with prompt + PDF builder.

---

## P8 — Dashboard (living PDP)

**Exit:** user edits a plan in the UI; assistant proposes tasks from chat/PDP and user approves; progress renders.

- [ ] **(B)** Confirm `goals`/`milestones`/`tasks`/`progress_entries` tables (from P2) + any refinements.
- [ ] **(B)** `api/dashboard.py` — CRUD goals/milestones/tasks, log progress, summary endpoint (`GET /api/dashboard`).
- [ ] **(B)** Expose dashboard as **native tools** (read + propose); AI writes user-scoped, `source=ai`, confirmable (proposed → approved), never silent.
- [ ] **(B)** PDP generation **seeds** goals/tasks into the dashboard.
- [ ] **(F)** Dashboard UI: goals/tasks board, progress charts/streaks, % to target date; approve/reject AI proposals.
- [ ] **(T)** User edits plan; assistant proposes tasks; approval flow; progress renders.

---

## P9 — Personalization (teachable memory) + response feedback

**Exit:** across two sessions assistant adapts to a stated preference; a 👎 changes future behavior; user can inspect & delete what was learned.

- [ ] **(B)** `message_feedback` capture: 👍/👎 + optional reason — `POST /api/messages/{message_id}/feedback`.
- [ ] **(B)** `memory/` on **LangMem** (in-process, over pgvector `user_memories`) — recall step (explicit prefs + top-k `user_memories` → context) wired into the graph before the planner.
- [ ] **(B)** Learn step as a Celery task post-turn (LangMem extract/update): durable prefs, dedup/update, confidence; thumb-down demotes/removes.
- [ ] **(D)** Resolve the open decision — learned-memory application **silent-but-viewable vs require confirmation** — and implement the chosen behavior.
- [ ] **(B)** Responder adapts tone/depth to recalled preferences.
- [ ] **(B)** `GET/PUT/DELETE /api/memory` (view/edit/delete learned memories + preferences).
- [ ] **(B)** Guests: personalization session-only (Redis); account upgrade persists it.
- [ ] **(F)** 👍/👎 on messages + inline "try again"; "What the coach knows about you" panel.
- [ ] **(T)** Cross-session adaptation; 👎 changes behavior; inspect + delete memories.

---

## P10 — Security & guardrails

**Exit:** jailbreak/injection test suite passes; no secret/prompt leakage; no arbitrary code execution.

- [ ] **(B)** Input guardrails: jailbreak / prompt-injection detection, abuse/off-topic filter, PII scrub before tools/external calls.
- [ ] **(B)** Output guardrails: block system-prompt leakage, strip injected instructions echoed from crawled pages.
- [ ] **(B)** Confirm v1 `run_python_code` REPL is **removed** (ACE risk); sandboxed evaluator only if math truly needed.
- [ ] **(B)** Per-session/per-tool rate-limit enforcement + abuse handling; treat all crawled/web content as untrusted.
- [ ] **(T)** Jailbreak/injection test suite; secret/prompt-leak checks; no arbitrary code execution.

---

## P11 — Deploy, parity & cutover

**Exit:** v2 live on HF Spaces at full parity + new features; v1 removed.

- [ ] **(I)** HF Spaces Dockerfile: build Next.js + run FastAPI (single container).
- [ ] **(I)** Run Celery worker co-located in the Space container.
- [ ] **(I)** Wire **self-hosted datastores** (Postgres+pgvector + Redis co-located containers; **no managed tier** for now) via Space secrets. (Managed tier = escape hatch if Spaces persistence needed.)
- [ ] **(T)** Parity checklist vs v1 (chat, PDP, job search, feedback) + smoke tests.
- [ ] **(I)** Observability: structured logging, agent traces, error tracking.
- [ ] **(I)** Cut over to v2.
- [ ] **(I)** Delete v1: `app.py`, `output_parser.py`, old CRA `frontend/`, `helpers/feedback_handler.py` JSON store, etc.

---

## Cross-cutting / definition-of-done

- [ ] Every endpoint flows Router → Service → (Agent/Repository); no driver access in services.
- [ ] All secrets via env / Space secrets — never committed.
- [ ] Free/OSS/self-hosted by default (§11); paid only behind explicit opt-in.
- [ ] Update CLAUDE.md as each phase lands (mark decisions resolved, drop v1 notes once removed).
