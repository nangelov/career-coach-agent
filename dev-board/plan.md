# Career Coach Agent — Refactor Plan

> Execution plan for the v2 rebuild. Companion to [app-design-and-features.md](./app-design-and-features.md).
> Strategy: **Foundation first, then features.** Build the new skeleton (backend + datastores + agent graph + frontend shell) end-to-end, then layer features behind it.
> Status: **Proposed** · Last updated: 2026-06-28 (all 9 pre-work decisions locked; only learned-memory application open)

---

## Guiding principles

- **Don't migrate v1 in place.** Stand up `backend/` and a Next.js `frontend/` alongside the old code; cut over once parity is reached, then delete v1.
- **Vertical "walking skeleton" first** — a trivial end-to-end path (UI → FastAPI → 1 agent → LLM → stream back) before any real feature, so integration risk is paid down early.
- **Interfaces before implementations** — `LLMClient`, `DocumentParser`, repositories, and guardrails are interfaces from day one so engines/providers can be swapped.
- **Each phase ends in a runnable, demoable state.**

---

## Phase 0 — Decisions & Scaffolding (foundation)

**Goal:** lock the choices that are expensive to change later, and get an empty app running.

- [x] Decisions from design §6 locked: orchestration = **LangGraph**, auth = **SSO (Google+LinkedIn) backend-owned**, embeddings = **`Qwen/Qwen3-Embedding-8B`** (**vector dim 4096**), guest rate-limit = **10 msgs + 1 doc/session**, failover = **`Qwen/Qwen3.6-27B` secondary, no paid last-resort**, mid-stream = **resume**, memory = **LangMem**, datastores = **self-hosted Postgres + Redis**. (Only open item: learned-memory silent-vs-confirm → P9.)
- [ ] Verify the **primary tool-calling model `zai-org/GLM-5.2`** runs native `tools=[...]` via HF Inference Providers (OpenAI-compatible) with a throwaway script.
- [ ] New repo layout per design §8: `backend/` (FastAPI, `pyproject.toml` via **uv**), `frontend/` (Next.js App Router + TS).
- [ ] `docker-compose.yml` for local dev: app + **Celery worker** + Postgres(+pgvector) + Redis (Redis doubles as Celery broker). **No Mongo** — Postgres JSONB covers documents (§4).
- [ ] `config.py` with `pydantic-settings`; all secrets via env / Space secrets.
- [ ] CI: lint/format/type (ruff + mypy backend; eslint/tsc frontend) + test stubs.

**Exit criteria:** `docker compose up` starts FastAPI + Celery worker + 3 databases + Next.js; health check green; a trivial Celery task round-trips through Redis.

---

## Phase 1 — Walking Skeleton: streaming chat, one agent

**Goal:** one real end-to-end path with native tool-calling and streaming — no multi-agent yet.

- [ ] `LLMClient` interface + HF implementation (native tool-calling; **no ReAct text parsing**).
- [ ] **LLM failover router** (§6.6): ordered models, per-call timeout, retry/backoff, Redis circuit-breaker. Build it into the interface now so everything downstream inherits reliability.
- [ ] Define 1–2 tools with proper JSON schemas (e.g. `current_date_and_time`, `internet_search`) as the native-tool pattern.
- [ ] `POST /api/chat` with **SSE streaming**; tool-call loop driven by the model.
- [ ] Redis-backed **per-session memory** + cancel/stop (replaces global memory + in-process dict).
- [ ] Per-message `message_id` on every assistant message (foundation for feedback §5.5).
- [ ] Next.js chat page: streaming render, stop button, visible tool steps.

**Exit criteria:** a user can chat, the model calls a tool, the answer streams token-by-token, stop works, and killing the primary model endpoint transparently fails over. **`output_parser.py` is gone.**

---

## Phase 2 — Persistence foundation & repositories

**Goal:** the data layer all features depend on.

- [ ] Repository layer: `postgres.py` (SQLAlchemy/SQLModel + JSONB + pgvector), `redis.py` — services never touch drivers directly.
- [ ] Postgres + **alembic** migrations — **identity/docs (JSONB):** `users`, `profiles`, `preferences`, `sessions`, `conversations`/`messages`, `message_feedback`, `feedback`; **knowledge/vectors:** `kb_documents`, `kb_chunks(embedding vector(4096))`, `user_memories(embedding vector(4096))` (dim fixed by `Qwen/Qwen3-Embedding-8B`); **structured:** `jobs`, `pdps`, dashboard (`goals`/`milestones`/`tasks`/`progress_entries`).
- [ ] `EmbeddingClient` — **in-process `sentence-transformers` `Qwen/Qwen3-Embedding-8B`** (4096-dim) + pgvector write/similarity-search helpers.
- [ ] Persist Phase 1 conversations to Postgres for **logged-in** users; **guests stay Redis-only**.

**Exit criteria:** chat history survives restart for accounts; vector insert + similarity query verified.

---

## Phase 3 — Auth, sessions & guest mode

**Goal:** identity and the guest/account split.

- [ ] `POST /api/auth/guest` → anonymous session (Redis, TTL, no history).
- [ ] **SSO login (Google + LinkedIn) via Authlib OIDC**, backend-owned: `/api/auth/login/{provider}` + `/callback` with **PKCE**; mint short-lived session JWT; FastAPI verify dependency. **No passwords stored.**
- [ ] Provider setup: OAuth apps for Google + LinkedIn; client secret + JWT key in **HF Space Secrets**; **redirect URIs locked** to the Space domain; **minimal scopes** (`openid email profile`).
- [ ] **Guest → account upgrade** preserves the active session.
- [ ] AuthZ: users access only their own data; per-session/user **rate limits** in Redis.
- [ ] Replace v1 `GET /get-feedback?key=<HF_TOKEN>` with real admin auth.

**Exit criteria:** guest and logged-in flows both work; upgrade carries the session; access control enforced.

---

## Phase 4 — Multi-agent orchestration

**Goal:** replace the single agent with the planner→workers→responder graph (design §3).

- [ ] LangGraph graph + typed shared `state.py`.
- [ ] **Planner** (intent classify, decompose, route, budget).
- [ ] **Response Agent** (synthesize, cite, format, stream).
- [ ] **RAG Agent** against pgvector (grounded snippets + citations).
- [ ] **Web Searcher + Crawler** — search + crawl job/role pages; crawled content treated as **untrusted data**.
- [ ] Streaming surfaces planner/worker steps to the UI.

**Exit criteria:** a query routes through planner → ≥1 worker → responder, streams, and cites sources.

---

## Phase 5 — Document Intelligence & CV/profile

**Goal:** robust CV ingestion incl. **OCR** (design §5.1), feeding the profile + RAG.

- [ ] `DocumentParser` interface in `ingestion/`; **docling** as primary engine.
- [ ] Type detect + text-layer check; **OCR fallback** (Tesseract/OCRmyPDF) for scanned/image/slide CVs; reserve a **VLM-OCR** path for hard docs.
- [ ] Layout-aware structuring → LLM-assisted parse → **structured profile** (skills/experience/education/goals).
- [ ] `POST /api/profile/cv` runs parsing as a **Celery task** (progress via Redis) → store profile (Postgres JSONB), embed chunks into pgvector.
- [ ] `GET/PUT /api/profile`; reuse profile across chats (no re-upload).

**Exit criteria:** a **scanned/image PDF and a PPTX CV** both parse (async, with progress) into a usable structured profile and become RAG-grounded.

---

## Phase 6 — Richer job search

**Goal:** upgrade beyond v1's single Google Jobs call.

- [ ] **Job Search Agent**: multi-source, normalized listings, dedup into Postgres `jobs`.
- [ ] Filters (location/remote/salary); **profile-aware match scoring**.
- [ ] Crawl + extract structured role profiles (skills/requirements) via the web crawler, run as **Celery tasks**.
- [ ] Save/track jobs per user; cache hot queries in Redis.
- [ ] `GET/POST /api/jobs`.

**Exit criteria:** filtered, deduped, profile-scored results; users can save jobs; repeat queries hit cache.

---

## Phase 7 — PDP generator (rebuilt)

**Goal:** same styled-PDF output, driven by structured profile + RAG.

- [ ] **PDP Agent**: structured profile + RAG-grounded recommendations → structured PDP sections.
- [ ] Keep reportlab builder (port `helpers/helper.py` → `pdf/`); keep section-header contract + validation gate.
- [ ] `POST /api/pdp` uses the **stored profile** (no re-upload); regenerate on demand.

**Exit criteria:** PDP PDF matches/exceeds v1 quality, grounded in the user's stored profile.

---

## Phase 8 — Dashboard (living PDP)

**Goal:** turn the one-shot PDP into a trackable plan the user and AI co-manage (design §5.2).

- [ ] Postgres tables + migrations: `goals`, `milestones`, `tasks`, `progress_entries`.
- [ ] `dashboard.py` router: CRUD goals/milestones/tasks, log progress, summary endpoint.
- [ ] Next.js dashboard UI: goals/tasks board, progress charts/streaks, % to target date.
- [ ] PDP generation **seeds** goals/tasks into the dashboard.
- [ ] Expose dashboard as **native tools** so the AI can read + **propose** changes; AI writes are user-scoped, `source=ai`, and **confirmable** (proposed → approved), never silent.

**Exit criteria:** user edits a plan in the UI; the assistant can propose tasks from chat/PDP and the user approves them; progress renders.

---

## Phase 9 — Personalization (teachable memory) + response feedback

**Goal:** the assistant learns each user and collects per-message signal (design §5.4–5.5).

- [ ] `message_feedback` capture: 👍/👎 (approve/disapprove) + optional reason on each assistant message; inline "try again".
- [ ] `memory/` module on **LangMem** (in-process, over the pgvector `user_memories` store): **recall** step (explicit prefs + top-k `user_memories` → context) wired into the graph before the planner.
- [ ] **Learn** step as a **Celery task** post-turn (LangMem extract/update): durable preferences, dedup/update, confidence; thumb-down demotes/removes.
- [ ] **Decide open item: learned-memory application — silent-but-viewable vs require confirmation** (the one pre-work decision left TBD); implement the chosen behavior here.
- [ ] Responder adapts tone/depth to recalled preferences.
- [ ] `GET/PUT/DELETE /api/memory` + a "What the coach knows about you" panel (view/edit/delete).
- [ ] Guests: personalization session-only (Redis); account upgrade persists it.

**Exit criteria:** across two sessions the assistant visibly adapts to a stated preference; a 👎 changes future behavior; user can inspect & delete what was learned.

---

## Phase 10 — Security & Guardrails

**Goal:** harden input/output (design §7). *Note: input guardrails land minimally in Phase 4 and are completed here.*

- [ ] Input guardrails: jailbreak / prompt-injection detection, abuse/off-topic filter, PII scrub before tools/external calls.
- [ ] Output guardrails: block system-prompt leakage, strip injected instructions echoed from crawled pages.
- [ ] Confirm the v1 `run_python_code` REPL is **removed** (ACE risk); sandboxed evaluator only if math is truly needed.
- [ ] Rate-limit + abuse tests; treat all crawled/web content as untrusted.

**Exit criteria:** a jailbreak/injection test suite passes; no secret/prompt leakage; no arbitrary code execution.

---

## Phase 11 — Deploy, parity & cutover

**Goal:** ship to HF Spaces and retire v1.

- [ ] HF Spaces Dockerfile: build Next.js + run FastAPI (single container).
- [ ] Wire **self-hosted datastores** (Postgres+pgvector + Redis as co-located containers; **no managed tier** for now — §11) with connection strings via Space secrets. (Managed tier = documented escape hatch if Spaces persistence is needed.)
- [ ] Run the **Celery worker** as a co-located process in the Space container.
- [ ] Parity checklist vs v1 (chat, PDP, job search, feedback) + smoke tests.
- [ ] Observability: structured logging, agent traces, error tracking.
- [ ] **Cut over**, then delete v1 (`app.py`, `output_parser.py`, old `frontend/` CRA, etc.).

**Exit criteria:** v2 live on HF Spaces at full parity + new features; v1 removed.

---

## Sequencing summary

```
P0 Scaffolding ─▶ P1 Skeleton (stream + failover + 1 tool) ─▶ P2 Persistence ─▶ P3 Auth/guest
   ─▶ P4 Multi-agent ─▶ P5 Doc-intel/CV+OCR ─▶ P6 Jobs ─▶ P7 PDP
   ─▶ P8 Dashboard ─▶ P9 Personalization+Feedback ─▶ P10 Guardrails ─▶ P11 Deploy
```

Foundation = **P0–P3** (skeleton, reliability, data, identity). Features = **P4–P9**. Hardening + ship = **P10–P11**.
Reliability (LLM failover) and async infra (Celery) land in the foundation so every feature inherits them. Guardrails are introduced minimally once the agent graph exists (P4) and *completed* in P10 — security isn't bolted on last, only finished there.

---

## Cost posture (budget-constrained — prefer free / OSS / self-hosted)

Everything is chosen to run at **zero or near-zero cost** (design §11):
- **LLM [decided]:** HF Inference free allowance; failover **`zai-org/GLM-5.2` → `Qwen/Qwen3.6-27B`** (both free OSS) doubles as the budget strategy — **no paid last-resort**.
- **Embeddings [decided]:** **`Qwen/Qwen3-Embedding-8B` via `sentence-transformers` in-process** (free, no API) — sets pgvector to **`vector(4096)`** — instead of a paid embedding endpoint.
- **Auth:** **backend SSO** (Authlib + Google/LinkedIn OIDC) — free, no password storage, no extra service.
- **Datastores [decided]:** **Postgres + Redis only, self-hosted** via `docker-compose` (local) + co-located on Spaces — **no managed tier** for now. Postgres JSONB + pgvector absorbs Mongo's role; rationale is single-container simplicity, not cost (§4 / §11). Managed tier (Neon/Supabase + Upstash) is the escape hatch if Spaces persistence is required.
- **Teachable memory [decided]:** **LangMem** in-process over the pgvector `user_memories` store — no external memory service (§6.7).
- **Doc-intel/OCR, guardrails, Celery, crawler:** all OSS/self-hosted (docling, Tesseract, Llama-Guard/regex, Celery, crawl4ai/playwright).

## Decisions locked before P1 (was: open items)

All pre-work decisions are now **locked** (see design §6 / CLAUDE.md). One item remains open (8).

1. **Orchestration → LangGraph** [DECIDED] (hand-rolled orchestrator rejected).
2. **Primary tool-calling model → `zai-org/GLM-5.2`** via HF Inference Providers (OpenAI-compatible) [DECIDED]. **Embedding model → `Qwen/Qwen3-Embedding-8B`**, in-process `sentence-transformers`, **output dimension 4096 → pgvector `vector(4096)`** [DECIDED].
3. **Datastores → Postgres + Redis only, self-hosted** [DECIDED]. Mongo consolidated into Postgres JSONB; **no managed tiers** (Neon/Supabase/Upstash) for now — `docker-compose` locally + co-located on Spaces.
4. **LLM failover → secondary `Qwen/Qwen3.6-27B`, no paid last-resort** [DECIDED]. **Guest rate-limit → 10 messages + 1 document upload per guest session** [DECIDED].
5. **Mid-stream failover → resume** (continue the in-flight stream on the secondary model, not restart-with-notice) [DECIDED].
6. **Teachable memory → LangMem** (in-process, over the pgvector `user_memories` store) [DECIDED] — supersedes the earlier "custom pgvector" choice; natural fit with LangGraph, avoids custom recall/learn, no external service (design §6.7).
7. **Learned-memory application (silent vs require confirmation) → TBD / OPEN** — to be decided in **P9** (design §5.4 / §6.7).
