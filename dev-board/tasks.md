# Career Coach Agent — Development Tasks

> Actionable task breakdown for the v2 rebuild. Derived from [plan.md](./plan.md) (phases P0–P12) and [app-design-and-features.md](./app-design-and-features.md).
> Convention: tasks are grouped by phase; each phase ends in a runnable/demoable state. `[ ]` = todo, `[~]` = in progress, `[x]` = done.
> Tags: **(B)** backend · **(F)** frontend · **(I)** infra/devops · **(D)** decision · **(T)** test/verify.
> **2026-07-13 (later) revision:** from **P6 onward**, every phase closes with a dedicated **(T) CI/CD
> verification** task — run the full backend + frontend CI command sets **locally** (the same commands
> `.github/workflows/backend-ci.yml` / `frontend-ci.yml` run: ruff + mypy + pytest; eslint + tsc + jest) and
> confirm both are green before the phase is considered done. (The project's CI runs on **GitHub Actions**,
> not GitLab — CLAUDE.md/`dev-board/plan.md` already say so; this step just means "run the CI pipeline's own
> commands ahead of pushing," whichever host runs them.)
> **2026-07-13 revision:** product scope locked to coaching/personal-development (§1.1) → **P6 rescoped** from
> *"Richer job search"* to **Market intelligence**; a new **[SEC]** block lands between P5 and P6; P9/P10
> extended with privacy, topic-scoping and abuse work; **new P11 "Observability, telemetry & product analytics"**
> (OpenTelemetry + Sentry + GA4) inserted before the 🛑 pre-go-live review, shifting the old P11 to **P12**.
> Open decisions are listed at the bottom of this file.

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

- [x] **(B)** `ingestion/` — `DocumentParser` interface; **docling** as primary engine.
- [x] **(B)** Type detect + text-layer check; OCR fallback (Tesseract/OCRmyPDF) for scanned/image/slide CVs; reserve VLM-OCR path for hard docs.
- [x] **(B)** Layout-aware structuring → LLM-assisted parse → structured profile (skills/experience/education/goals).
- [x] **(B)** `POST /api/profile/cv` runs parsing as a **Celery task** (progress via Redis) → store profile (JSONB) + embed chunks into pgvector.
- [x] **(B)** `GET/PUT /api/profile`; reuse profile across chats (no re-upload).
- [x] **(B)** `GET /api/jobs/status/{task_id}` — poll async task progress.
- [x] **(F)** CV upload UI + progress indicator; profile view/edit.
- [x] **(T)** Scanned/image PDF and PPTX CV both parse async into a structured profile and are RAG-grounded.

---

## SEC — Security & privacy hardening (runs between P5 and P6)

**Why here:** the app isn't live, so nothing is a hotfix — but S1/S2 are *entrenched by P6* and S4/S6 get more
expensive with every authed surface added. Ordered by cost-to-unwind (plan.md → "Security & privacy sequencing").

- [x] **(B) S1 — SSRF guard** (design §7.2): a single outbound-fetch guard used by *every* crawler/tool — http(s) schemes only; reject private / loopback / link-local resolved IPs (incl. `169.254.169.254`); bounded redirects **re-validated on each hop**; host allow/deny list; timeout + response-size caps. *(Today `web_searcher.py` does `follow_redirects=True` with no validation — highest-severity code gap.)*
- [x] **(B) S2 — Untrusted-content contract** (design §7.3): fence CV/OCR text, crawled pages, postings and search snippets as **data, never instructions**; **no tool-call may be initiated by untrusted text**; keep extraction on a forced/constrained schema.
- [x] **(I) S5 — Compose port lockdown** (design §7.2): remove host port mappings for `db` (5432), `redis` (6379) and `backend` (8000); publish **only** the Next.js port; move local-dev exposure to an opt-in override file.
- [x] **(B/F) S4 — BFF + httpOnly cookie** (design §6.13 / §7.2): move the session from `localStorage` + Bearer-in-JS to **Next.js Route Handlers** holding an httpOnly · Secure · SameSite cookie and injecting `Authorization` **server-side**; OIDC callback sets the cookie (**no token in the URL fragment**); SSE passthrough preserved. *Do before P8 adds more authed surface.*
- [x] **(B) S6 — GDPR erasure + export**: `DELETE /api/me` (Art. 17 — cascades Postgres rows, Redis session state, Celery artifacts) and `GET /api/me/export` (Art. 20).
- [x] **(B/F) S13 — Consent gate** (§6.22): ToS + privacy acceptance **required to mint a session** — checkbox at SSO login (persist `user_id`, policy version, timestamp → re-prompt on version bump) and at **every** guest-session start. Ship with S4, which is already rewriting session creation.
- [x] **(F/B)** Privacy notice + ToS pages. Must state plainly: **CV text is sent to a third-party LLM provider with contact details redacted**; retention ≤30 days (SSO) / session-only (guest); **data may be lost on restart** (§6.17).
- [x] **(B) S10 — Contact-detail redaction at the LLM egress boundary** (§6.16): one chokepoint in the `llm/` layer — name, email, phone, postal address, personal links, photo. **Keep** employers/titles/dates/skills/education. *Not scattered across agents.*
- [x] **(T)** SSRF probes (loopback / link-local / redirect-to-private) blocked; an injected instruction inside a CV and inside a crawled page is **not** followed; only the UI port is reachable from the host; token absent from JS/`localStorage`/URL; delete-account leaves no orphan rows.

---

## P6 — Market intelligence (role requirements)

> **RESCOPED** (design §1.1 / §5.6 / §6.11) — was *"Richer job search"*. **Not a job board.** Job postings are
> **evidence of market requirements**, never browsable inventory. **Dropped:** listings UI, location/remote/salary
> filters, save/track jobs, per-posting match scoring, `GET/POST /api/jobs`.

**Exit:** for a target role, the app returns **cited, frequency-ranked market requirements** (taxonomy baseline +
posting delta) and a **skills gap** vs the user's profile. Extraction happens **once per role**, reused across
users. **No job listings are ever shown.**

- [x] **(B)** **Taxonomy seed (no scraping)** — ingest **ESCO / O\*NET** occupations + skills into the **shared** KB (`kb_documents.user_id IS NULL`). *This finally populates the RAG corpus, which no phase previously owned.*
- [x] **(B)** Migration: **`role_profiles`** — canonical role + taxonomy id, `requirements JSONB` (skill → frequency/weight/evidence), sources, `evidence_count`, `refreshed_at`. **Global, not user-scoped.**
- [x] **(B)** Migration: **`job_postings`** (was `jobs`) — raw **evidence only**, TTL-cached, deduped, **third-party PII stripped at ingest** (recruiter name/email/phone — they never consented).
- [x] **(B)** `agents/market_agent.py` (was `job_agent.py`) — normalize target role → taxonomy baseline → mine postings for the recency delta → aggregate → write `role_profiles` + embed into pgvector.
- [x] **(B)** Mining as **Celery tasks**; all fetched content is **untrusted** (S2) and every fetch uses the **SSRF guard** (S1).
- [x] **(B)** **Skills gap**: user profile △ `role_profile` → the input to P7's PDP.
- [x] **(B)** **Tavily search provider + 3-key rotating pool** (§5.7 / §6.19): `TAVILY_API_KEY_1|2|3` from Space Secrets; ordered failover, **promote the surviving key to primary** (persisted in Redis so a dead/exhausted key isn't retried every call), quota-aware. **Reuse the `llm/router.py` failover pattern — do not invent a second mechanism.** Replaces SerpAPI in `tools/internet_search.py`.
- [x] **(B)** **Learning-resource corpus** (§5.7 / §6.20): crawl Coursera / Udacity / Udemy / edX (and similar) → normalized (title, provider, level, duration, cost, URL, **skills covered**), **skill-keyed**, shared (`user_id IS NULL`), embedded, TTL-refreshed via Celery. Prefer official catalogs/APIs over scraping marketing pages. Cited whenever the PDP recommends them.
- [x] **(B)** `GET /api/roles/{role}/requirements` + `GET /api/roles/{role}/gap`; Redis cache for hot roles; periodic refresh of stale profiles. **No user-facing turn triggers uncached crawling** — mining is always a Celery job (quota protection, §7.5).
- [x] **(B)** **S3 — Topic guardrail** (design §7.4) on the planner's **existing** `Intent` classification (no extra LLM call): `OFF_TOPIC` → refuse; `JOB_HUNTING` → **redirect** to market requirements. Low false-positives on legitimate career questions.
- [x] **(I)** Source policy: respect `robots.txt`, rate-limit, **never scrape LinkedIn** (ToS).
- [x] **(F)** Role-requirements UI: target role, frequency-ranked skills **with citations**, gap vs profile. **No listings, no apply, no save/track.**
- [x] **(T)** "PM → AI Solution Architect" returns cited, ranked requirements + a gap; second user hits the cache (no re-extraction); *"find me jobs in Berlin"* is **redirected**, not answered with listings.
- [x] **(T)** **CI/CD verification** — run the full backend + frontend CI command sets locally (ruff + ruff format --check + mypy + pytest; eslint + tsc + jest — the exact commands in `.github/workflows/backend-ci.yml` / `frontend-ci.yml`) and confirm both are green before closing the phase.

---

## P7 — PDP generator (rebuilt)

**Exit:** PDP PDF matches/exceeds v1 quality, grounded in the user's stored profile.

- [x] **(B)** `agents/pdp_agent.py` — structured profile + RAG-grounded recommendations → structured PDP sections.
- [x] **(B)** Port `helpers/helper.py` reportlab builder → `pdf/`; keep section-header contract + `validate_pdp_response` gate.
- [x] **(B)** `POST /api/pdp` uses the **stored profile** (no re-upload); regenerate on demand.
- [x] **(F)** PDP generation UI (uses stored profile) + download.
- [x] **(T)** PDP PDF quality vs v1; section headers stay in sync with prompt + PDF builder.
- [x] **(T)** **CI/CD verification** — run the full backend + frontend CI command sets locally (ruff + ruff format --check + mypy + pytest; eslint + tsc + jest — the exact commands in `.github/workflows/backend-ci.yml` / `frontend-ci.yml`) and confirm both are green before closing the phase.

---

## P8 — Dashboard (living PDP)

**Exit:** user edits a plan in the UI; assistant proposes tasks from chat/PDP and user approves; progress renders.

- [x] **(B)** Confirm `goals`/`milestones`/`tasks`/`progress_entries` tables (from P2) + any refinements.
- [x] **(B)** `api/dashboard.py` — CRUD goals/milestones/tasks, log progress, summary endpoint (`GET /api/dashboard`).
- [x] **(B)** Expose dashboard as **native tools** (read + propose); AI writes user-scoped, `source=ai`, confirmable (proposed → approved), never silent.
- [x] **(B)** PDP generation **seeds** goals/tasks into the dashboard.
- [x] **(F)** Dashboard UI: goals/tasks board, progress charts/streaks, % to target date; approve/reject AI proposals.
- [x] **(T)** User edits plan; assistant proposes tasks; approval flow; progress renders.
- [x] **(T)** **CI/CD verification** — run the full backend + frontend CI command sets locally (ruff + ruff format --check + mypy + pytest; eslint + tsc + jest — the exact commands in `.github/workflows/backend-ci.yml` / `frontend-ci.yml`) and confirm both are green before closing the phase.
- [x] **(I)** **Guard against curated-CI-dependency drift** — backend CI deliberately runs a hand-curated `uv pip install <light-deps>` list (not a full `uv sync`) to avoid pulling the heavy ML stack (torch/docling), mirrored in `backend/Makefile`'s `install` target. This exact class of bug ("a new always-imported runtime dep lands in `pyproject.toml` but nobody adds it to the curated list") has broken the real pipeline **six times** across P1–P7 (FIX-01, FIX-02, FIX-03, FIX-04, FIX-09, FIX-11 — most recently `reportlab`, P7-02). Add an automated guard so it can't recur silently: a small script/test (e.g. `scripts/check_curated_deps.py` or a `pytest` case) that statically walks `app/`'s imports (or diffs `pyproject.toml`'s light/runtime deps against the curated list, excluding an explicit ML-stack allowlist) and fails with a clear message naming the missing package — wired as an early step in `backend-ci.yml` (and/or a pre-commit/`make lint` check) so a future PR that adds a new light dependency fails fast locally instead of only surfacing in a real `pytest` collection error on `main`/`version-2` after merge.

---

## P9 — Personalization (teachable memory) + response feedback

**Exit:** across two sessions assistant adapts to a stated preference; a 👎 changes future behavior; user can inspect & delete what was learned.

- [x] **(B)** `message_feedback` capture: 👍/👎 + optional reason — `POST /api/messages/{message_id}/feedback`.
- [x] **(B)** `memory/` on **LangMem** (in-process, over pgvector `user_memories`) — recall step (explicit prefs + top-k `user_memories` → context) wired into the graph before the planner.
- [x] **(B)** Learn step as a Celery task post-turn (LangMem extract/update): durable prefs, dedup/update, confidence; thumb-down demotes/removes.
- [x] **(B)** **S7 — PII redaction before extraction** (design §7.6): durable `user_memories` are PII-free.
- [x] **(B)** **S7 — GDPR Art. 9 exclusion filter** (design §7.6): health / disability / ethnicity / religion / union / sexuality are **never** made durable (usable within the turn only). A career coach *will* receive these.
- [x] **(B)** Learned-memory application = **silent-but-viewable/deletable (opt-out)** [DECIDED §6.10] — memory panel, no per-fact confirmation prompts.
- [x] **(B)** Responder adapts tone/depth to recalled preferences.
- [x] **(B)** `GET/PUT/DELETE /api/memory` (view/edit/delete learned memories + preferences).
- [x] **(B)** Guests: personalization session-only (Redis); account upgrade persists it.
- [x] **(B)** **S14 — Retention purge** (§6.18): periodic Celery job deleting SSO users' conversations / CVs / profiles / memories / traces **30 days after last activity**; guests expire with the session TTL.
- [x] **(F)** 👍/👎 on messages + inline "try again"; "What the coach knows about you" panel.
- [x] **(T)** Cross-session adaptation; 👎 changes behavior; inspect + delete memories.
- [x] **(T)** **CI/CD verification** — run the full backend + frontend CI command sets locally (ruff + ruff format --check + mypy + pytest; eslint + tsc + jest — the exact commands in `.github/workflows/backend-ci.yml` / `frontend-ci.yml`) and confirm both are green before closing the phase.

---

## P10 — Security & guardrails

**Exit:** jailbreak/injection test suite passes; no secret/prompt leakage; no arbitrary code execution.

- [ ] **(B)** **S8 — Real injection classifier** replacing the P4 regex deny-list (Prompt-Guard / Llama-Guard). *The regex heuristic is an honest placeholder and stops nobody.*
- [ ] **(B)** Abuse / off-topic filter completed; **PII scrub before tools/external calls** (§7.6 — note the CV→LLM-provider disclosure decision, S10).
- [ ] **(B)** Output guardrails: block system-prompt leakage, strip injected instructions echoed from untrusted content.
- [ ] **(B)** Confirm v1 `run_python_code` REPL is **removed** (ACE risk); sandboxed evaluator only if math truly needed.
- [ ] **(B)** Per-session/per-user/**per-IP**/per-tool rate-limit enforcement + abuse handling; all crawled/web/**document** content untrusted.
- [ ] **(T)** Jailbreak/injection suite **including a CV with embedded injected instructions and a poisoned crawled page**; off-topic refused + job-hunting redirected; secret/prompt-leak checks; no arbitrary code execution.
- [ ] **(T)** **CI/CD verification** — run the full backend + frontend CI command sets locally (ruff + ruff format --check + mypy + pytest; eslint + tsc + jest — the exact commands in `.github/workflows/backend-ci.yml` / `frontend-ci.yml`) and confirm both are green before closing the phase.

---

## P11 — Observability, telemetry & product analytics

**Exit:** a full chat turn produces a trace with planner→worker→responder spans in the chosen OTel backend; a
forced error reaches Sentry; GA4 real-time shows a pageview + ≥1 custom event; traces/logs/GA payloads contain
no CV or message content.

- [ ] **(B)** OpenTelemetry instrumentation: FastAPI auto-instrumentation (requests) + manual spans for the LangGraph node graph (planner → workers → responder) + Celery task spans.
- [ ] **(B) S11 — PII redaction + retention limit** on traces/logs (§7.6) — traces would otherwise contain full CV text and every message; redact at the source.
- [ ] **(I)** OTLP exporter, env-configured endpoint/API key, targeting a free-tier hosted backend (owner's choice — Grafana Cloud free / Honeycomb free / similar). OTel is vendor-neutral, so this stays swappable; **no bespoke in-app telemetry dashboard** (YAGNI — use the backend's own UI).
- [ ] **(I) S15 — Sentry free tier** error notification, **PII scrubbing on**, low-noise alert rule (§6.24 / §7.7).
- [ ] **(D)** **Admin-access ruling:** access to the telemetry backend's dashboard is the provider's own login (recommend enabling Google sign-in there). **No new username/password admin surface is added to this app** — in-app admin actions keep using the existing `is_admin`-flagged SSO account (P3-05); the SSO-only decision (§6.2) is not reopened.
- [ ] **(F)** Reintroduce **Google Analytics 4** (`gtag.js`) in the Next.js frontend: pageviews + button-click engagement events (send-message, stop, upload-cv, generate-pdp, submit-feedback, thumbs up/down, dashboard actions) — mirrors the v1 `ChatBot.tsx` / `PDPDialog.tsx` pattern. Measurement ID via env; loads only after the consent gate (§6.22); **event payloads never carry message content, CV text, or PII.**
- [ ] **(T)** Verify a full chat turn traces end-to-end in the OTel backend; force an error and confirm it reaches Sentry; confirm GA4 real-time events; grep exported traces/logs/GA payloads for CV/message content — none found.
- [ ] **(T)** **CI/CD verification** — run the full backend + frontend CI command sets locally (ruff + ruff format --check + mypy + pytest; eslint + tsc + jest — the exact commands in `.github/workflows/backend-ci.yml` / `frontend-ci.yml`) and confirm both are green before closing the phase.

---

## P12 — Deploy, parity & cutover

**Exit:** v2 live on HF Spaces at full parity + new features (including P11 observability/analytics reporting real data); v1 removed.

### 🛑 PRE-GO-LIVE REVIEW — blocking gate (owner + architect), before any cutover task below

- [ ] **(D)** **Sit down together and review before go-live.** Not a checklist re-run — a conversation about what the checklist *doesn't* cover. **Nothing ships until this happens and a go/no-go is explicitly recorded.**
  - [ ] **Critical-gaps sweep** — anything missing, half-done, or quietly deferred across P0–P11? Re-verify the **[SEC] block S1–S16** is genuinely done, not just ticked.
  - [ ] **Security & privacy sign-off** — SSRF guard, untrusted-content fencing, topic guardrail, BFF/httpOnly cookie, port lockdown, denial-of-wallet breakers, consent gate, retention purge, erasure + export. **Any "we'll fix it right after launch" item is a launch blocker by default.**
  - [ ] **Honesty check** — does the UI + privacy notice actually tell users: data **may be lost on restart** (§6.17), CV text goes to a **third-party LLM provider** with contact details redacted (§6.16), retention is ≤30 days / session-only (§6.18)?
  - [ ] **Scope check** — has anything crept back toward a job board / job assistant (§1.1 / §6.25)?
  - [ ] **Admin panel + audit trail** — deliberately deferred (§7.6); **design and scope it here.**
  - [ ] **Plan the next iteration** — what did we learn? Parked candidates: i18n / TTS / STT / voice agent (§6.23); managed datastore tier if durability starts to matter (§11); evaluation + regression gates on advice quality; scaling (k8s) *only if traffic ever justifies it*.
  - [ ] **(D)** Record an explicit **GO / NO-GO**.

- [ ] **(B)** Add HuggingFace credentials / secrets / API Keys whereever necessary to access LLMs
- [ ] **(I)** HF Spaces Dockerfile: build Next.js + run FastAPI (single container).
- [ ] **(I)** Run Celery worker co-located in the Space container.
- [ ] **(D)** **S12 — Datastore durability (OPEN):** a free Space is an **ephemeral container**, so self-hosted Postgres does **not** deliver P2's "history survives restart". Decide: managed free tier (Neon/Upstash — also free) vs paid persistent storage vs accept data loss. Then wire it via Space secrets.
- [ ] **(B/I)** **S9 — Denial-of-wallet gate:** per-IP guest-session creation limit (⚠️ HF Spaces is **behind a proxy** — read the client IP from `X-Forwarded-For` with a **trusted-proxy config**, or the header is spoofable and the limit is worthless); **Altcha proof-of-work** on guest creation (§6.21); **global daily LLM + Tavily budget breakers** (degrade to "at capacity", never exhaust the quota). **Blocks go-live.**
- [ ] **(I)** **S16 — Key-rotation runbook** (§7.7): document the one-liner — rotate `JWT_SECRET_KEY` / OAuth secret / `TAVILY_API_KEY_*` in Space Secrets → restart → all sessions invalidate. **No schedule, no IR programme** (right-sized for a free, non-critical app).
- [ ] **(I)** **S5 — Port lockdown in the Space image**: only the UI port reachable; FastAPI/Postgres/Redis internal-only.
- [ ] **(T)** Parity checklist vs v1 (chat, PDP, **market requirements**, feedback) + smoke tests. *(v1's job-listing search is intentionally **not** at parity — §1.1 scope ruling.)*
- [ ] **(T)** Confirm P11's OTel traces/Sentry/GA4 are wired and reporting from the deployed Space, not just locally.
- [ ] **(T)** **CI/CD verification** — run the full backend + frontend CI command sets locally (ruff + ruff format --check + mypy + pytest; eslint + tsc + jest — the exact commands in `.github/workflows/backend-ci.yml` / `frontend-ci.yml`) and confirm both are green before cutover.
- [ ] **(I)** Cut over to v2.
- [ ] **(I)** Delete v1: `app.py`, `output_parser.py`, old CRA `frontend/`, `helpers/feedback_handler.py` JSON store, etc.


---

## Cross-cutting / definition-of-done

- [ ] Every endpoint flows Router → Service → (Agent/Repository); no driver access in services.
- [ ] All secrets via env / Space secrets — never committed.
- [ ] Free/OSS/self-hosted by default (§11); paid only behind explicit opt-in.
- [ ] **Scope discipline (§1.1):** every feature serves *profile → gap → PDP → goals → progress*. **No job board, no general assistant, no medical/legal/financial advice.**
- [ ] **Untrusted content (§7.3):** any token the user did not type — CV/OCR text, crawled pages, postings, snippets — is **data, never instructions**.
- [ ] **Privacy (§7.6):** durable memories are PII-free and Art. 9-free; erasure cascades every store.
- [ ] Update CLAUDE.md as each phase lands (mark decisions resolved, drop v1 notes once removed).

---

## Decisions resolved 2026-07-13 (were open — now locked in design §6)

- [x] **(D) S10 — CV redaction → contact details only** [§6.16]. Strip name/email/phone/address/links/photo at the **LLM egress boundary**; keep employers, titles, dates, skills, education. Disclosed (Art. 13).
- [x] **(D) S12 — Datastore durability → accept data loss** [§6.17]. Free app, ephemeral Space, no managed tier, no backups. **Obligation:** UI + privacy notice must say data may be lost on restart.
- [x] **(D) Retention → SSO 30 days after last activity; guests session-only** [§6.18]. Periodic Celery purge.
- [x] **(D) Cover letters / CV tailoring / interview prep → OUT** [§6.25]. Job-assistant features; the product is coaching + personal development (§1.1).
- [x] **(D) Learning resources → crawl Coursera/Udacity/Udemy/edX via Tavily** [§6.20]; skill-keyed, shared corpus, cited in the PDP.
- [x] **(D) Search provider → Tavily, 3 rotating keys** (`TAVILY_API_KEY_1|2|3`) with failover + promote-to-primary, reusing the §6.6 router pattern [§6.19]. Replaces SerpAPI.
- [x] **(D) Bot protection → per-IP limit + Altcha proof-of-work** (OSS, self-hosted, no account) [§6.21].
- [x] **(D) Consent → ToS/privacy gate** on SSO login (recorded w/ policy version) and on **every** guest-session start [§6.22].
- [x] **(D) Language → English only** this iteration; i18n / TTS / STT / voice agent are future [§6.23].
- [x] **(D) Error notification → Sentry free tier** with PII scrubbing [§6.24]. **No IR programme; key rotation is a documented one-liner** (§7.7).
- [x] **(D) Admin panel + audit trail → deferred** to a pre-go-live phase; features to be designed then.
- [x] **(D) Observability → OpenTelemetry + free-tier OTLP backend** [§6.26]. Vendor-neutral traces/metrics/logs across FastAPI + LangGraph + Celery; PII-redacted, retention-limited; no bespoke in-app dashboard. Sentry (§6.24) stays the error-alerting channel. **Admin access to the telemetry backend = the provider's own login, not a new in-app password surface** — in-app admin stays on the existing `is_admin`-flagged SSO account (P3-05).
- [x] **(D) Product analytics → Google Analytics 4** [§6.27], reintroduced from v1's `gtag.js` pattern; pageviews + button-click engagement events only, no message/CV content, gated behind the consent screen.
- [x] **(D) New Phase 11 "Observability, telemetry & product analytics"** inserted after P10 guardrails and before the 🛑 pre-go-live review; the old Phase 11 (Deploy, parity & cutover) is now **Phase 12**.

## Still open

- [ ] **(D)** Nothing blocking today. **Next decision point is the 🛑 PRE-GO-LIVE REVIEW in P12** — a *blocking* owner + architect session covering: critical-gaps sweep, security/privacy sign-off, honesty of the user-facing notices, scope check, **admin panel + audit trail design**, and **next-iteration planning**. Nothing ships without a recorded go/no-go.
