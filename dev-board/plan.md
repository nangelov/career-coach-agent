# Career Coach Agent — Refactor Plan

> Execution plan for the v2 rebuild. Companion to [app-design-and-features.md](./app-design-and-features.md).
> Strategy: **Foundation first, then features.** Build the new skeleton (backend + datastores + agent graph + frontend shell) end-to-end, then layer features behind it.
> Status: **Proposed** · Last updated: 2026-07-13 — **scope + security revision**: P6 rescoped from *"Richer job search"* to **Market intelligence** (design §1.1 / §5.6 / §6.11); new **[SEC] block** between P5 and P6 (see "Security & privacy sequencing" below); P9/P10 extended with privacy, topic-scoping and abuse work; **new Phase 11 "Observability, telemetry & product analytics"** (OpenTelemetry + Sentry + GA4, design §7.8/§6.26–27) inserted after guardrails and before the 🛑 pre-go-live review, which shifted the old Phase 11 to **Phase 12 — Deploy, parity & cutover**.

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

## Phase 6 — Market intelligence (role requirements)

> **RESCOPED** (design §1.1 / §5.6 / §6.11). Was *"Richer job search"*. The app is **not a job board**: job
> postings are mined as **evidence of what the market requires**, never surfaced as browsable inventory.
> **Dropped from the old P6:** listings UI, location/remote/salary filters, save/track jobs, per-posting match
> scoring, `GET/POST /api/jobs`.

**Goal:** answer *"I'm a PM and want to become an AI Solution Architect — what does the market require?"*, and
turn that into a **skills gap** that feeds the PDP.

- [ ] **Taxonomy seed first (no scraping):** ingest **ESCO / O\*NET** occupations + skills into the **shared**
      KB (`kb_documents.user_id IS NULL`) — this is the corpus the RAG agent has been missing.
- [ ] **`role_profiles`** table + migration: canonical role, aggregated `requirements JSONB`
      (skill → frequency/weight/evidence), sources, `evidence_count`, `refreshed_at`. **Global, not user-scoped.**
- [ ] **`job_postings`** (was `jobs`): raw **evidence only**, TTL-cached, deduped, **third-party PII stripped at
      ingest** (recruiter name/email/phone).
- [ ] **Market Intelligence Agent** (`agents/market_agent.py`, was `job_agent.py`): normalize target role →
      taxonomy baseline → mine postings for the recency delta → aggregate → `role_profiles` + embed into pgvector.
- [ ] Mining runs as **Celery tasks**; postings and pages are **untrusted content** (§7.3) and every fetch goes
      through the **SSRF guard** (§7.2).
- [ ] **Skills gap**: user profile △ `role_profile` → the input to P7's PDP.
- [ ] **Search provider → Tavily with a rotating 3-key pool** (§5.7 / §6.19): `TAVILY_API_KEY_1|2|3` from Space
      Secrets; ordered failover + **promote-the-survivor to primary** (persisted in Redis). **Reuse the §6.6 LLM
      router pattern** — do not invent a second failover mechanism. *Replaces SerpAPI.*
- [ ] **Learning-resource corpus (§5.7):** crawl Coursera / Udacity / Udemy / edX (and similar) → normalized,
      **skill-keyed**, shared (`user_id IS NULL`), embedded, cited in the PDP. Prefer official catalogs/APIs over
      scraping marketing pages. TTL refresh via Celery.
- [ ] `GET /api/roles/{role}/requirements`, `GET /api/roles/{role}/gap`. Cache hot roles in Redis;
      periodic refresh of stale `role_profiles`.
- [ ] Source policy: respect `robots.txt`, rate-limit, **never scrape LinkedIn** (ToS).

**Exit criteria:** for a target role, the app returns **cited, frequency-ranked market requirements** (taxonomy
baseline + posting delta) and a **skills gap** against the user's profile. Extraction happens **once per role**
and is reused across users. **No job listings are ever shown.**

---

## Phase 7 — PDP generator (rebuilt)

**Goal:** same styled-PDF output, driven by structured profile + **the P6 skills gap** + RAG.

- [ ] **PDP Agent**: structured profile + **skills gap vs the target `role_profile` (P6)** + RAG-grounded recommendations → structured PDP sections.
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
- [ ] **PII redaction before extraction** — durable `user_memories` are PII-free (design §7.6).
- [ ] **GDPR Art. 9 exclusion filter** — health / disability / ethnicity / religion / union / sexuality are **never** made durable (usable within the turn only). A career coach *will* receive these (§7.6).
- [ ] Learned-memory application = **silent-but-viewable/deletable (opt-out)** [DECIDED §6.10] — implement the memory panel, no per-fact confirmation prompts.
- [ ] Responder adapts tone/depth to recalled preferences.
- [ ] `GET/PUT/DELETE /api/memory` + a "What the coach knows about you" panel (view/edit/delete).
- [ ] Guests: personalization session-only (Redis); account upgrade persists it.

**Exit criteria:** across two sessions the assistant visibly adapts to a stated preference; a 👎 changes future behavior; user can inspect & delete what was learned.

---

## Phase 10 — Security & Guardrails

**Goal:** harden input/output (design §7). *Note: input guardrails land minimally in Phase 4 and are completed here.*
*Several items below are **pulled earlier** — see "Security & privacy sequencing" at the end of this file.*

- [ ] Input guardrails: **real** jailbreak / prompt-injection classifier (the P4 regex deny-list is a placeholder and stops nobody) — e.g. Prompt-Guard / Llama-Guard.
- [ ] **Topic scoping (§7.4):** `OFF_TOPIC` → refuse, `JOB_HUNTING` → **redirect** to market requirements. Implemented on the planner's **existing** `Intent` classification — **no extra LLM call**. Tune for low false-positives on legitimate career questions.
- [ ] **Untrusted content (§7.3) — structural, not prompt-worded:** fencing for CV/OCR text, crawled pages, postings and snippets; **no tool-call may be initiated by untrusted text**; constrained-schema extraction; output guardrail strips echoed instructions.
- [ ] **SSRF guard on every outbound fetch (§7.2)** — http(s) only, reject private/loopback/link-local resolved IPs, bounded + re-validated redirects, host allow/deny list, timeouts and size caps. *(Do this before P6 crawls at scale.)*
- [ ] Output guardrails: block system-prompt leakage, strip injected instructions echoed from untrusted content.
- [ ] Confirm the v1 `run_python_code` REPL is **removed** (ACE risk); sandboxed evaluator only if math is truly needed.
- [ ] Rate-limit + abuse tests; treat all crawled/web/document content as untrusted.

**Exit criteria:** a jailbreak/injection test suite passes (**including a CV with embedded injected instructions** and a poisoned crawled page); off-topic is refused and job-hunting is redirected; SSRF probes to loopback/link-local are blocked; no secret/prompt leakage; no arbitrary code execution.

---

## Phase 11 — Observability, telemetry & product analytics

**Goal:** know when the app breaks and how people actually use it (design §7.8 / §6.26–27) — lands after
guardrails, before the pre-go-live review, so the review can inspect real telemetry instead of a promise of it.

- [ ] **OpenTelemetry instrumentation:** FastAPI auto-instrumentation (requests) + manual spans for the LangGraph
      node graph (planner → workers → responder) + Celery task spans.
- [ ] **S11 — PII redaction + retention limit** on traces/logs (design §7.6) — traces would otherwise contain full
      CV text and every message; redact at the source, not after the fact.
- [ ] **OTLP exporter**, env-configured endpoint/API key, targeting a free-tier hosted backend (owner's choice —
      Grafana Cloud free / Honeycomb free / similar). OTel keeps this swappable — no vendor lock-in, no bespoke
      in-app telemetry dashboard (YAGNI: use the backend's own UI).
- [ ] **S15 — Sentry free tier** error notification, PII scrubbing on, low-noise alert rule (design §6.24 / §7.7).
- [ ] **Admin-access ruling (no new endpoint):** access to the telemetry backend's dashboard is the provider's own
      login (recommend enabling Google sign-in there). This app does **not** grow a second, password-based admin
      surface — in-app admin actions keep using the existing `is_admin`-flagged SSO account (P3-05); the SSO-only
      decision (§6.2) is not reopened.
- [ ] **Google Analytics 4** in the Next.js frontend: `gtag.js` + pageviews + button-click engagement events
      (send-message, stop, upload-cv, generate-pdp, submit-feedback, thumbs up/down, dashboard actions) —
      mirrors the v1 `ChatBot.tsx` / `PDPDialog.tsx` pattern. Config via env (measurement ID); loads only after
      the consent gate (§6.22) is accepted; **event payloads never carry message content, CV text, or PII.**

**Exit criteria:** a full chat turn produces a trace with planner→worker→responder spans in the chosen OTel
backend; a forced error reaches Sentry; GA4 real-time shows a pageview + at least one custom event; traces, logs,
and GA payloads contain no CV/message content on inspection.

---

## Phase 12 — Deploy, parity & cutover

**Goal:** ship to HF Spaces and retire v1.

> ### 🛑 PRE-GO-LIVE REVIEW — a blocking checkpoint, owner + architect, before anything ships
>
> **Do not cut over until this conversation has happened.** P11 is the last point where a missing piece is
> cheap to add and the first point where a mistake is public. The purpose is *not* to re-run the task
> checklist — it is to ask what the checklist doesn't cover.
>
> **Agenda:**
> 1. **Critical gaps sweep** — what's missing, half-done, or was quietly deferred across P0–P11? Re-read the
>    [SEC] block (S1–S16): is every item *actually* done, or just ticked?
> 2. **Security & privacy sign-off** — SSRF guard, untrusted-content fencing, topic guardrail, BFF/cookie,
>    port lockdown, denial-of-wallet breakers, consent gate, retention purge, erasure/export. Any "we'll do it
>    right after launch" item is a **launch blocker** by default.
> 3. **Honesty check** — does the UI/privacy notice tell the truth about **data loss on restart** (§6.17),
>    CV text going to a third-party LLM provider (§6.16), and retention (§6.18)?
> 4. **Scope check** — has anything crept back toward a job board / job assistant (§1.1, §6.25)?
> 5. **Admin panel + audit trail** — deliberately deferred (§7.6); design and scope it *here*.
> 6. **Next-iteration planning** — what did we learn? Candidates parked so far: i18n / TTS / STT / voice agent
>    (§6.23), managed datastore tier if durability starts to matter (§11), evaluation/regression gates on
>    advice quality, scaling (k8s) *only if traffic ever justifies it*.
>
> **Exit:** an explicit, recorded **go / no-go** from the owner — not an implicit one.

- [ ] HF Spaces Dockerfile: build Next.js + run FastAPI (single container).
- [ ] **Port lockdown (§7.2):** publish **only** the Next.js port. Postgres / Redis / FastAPI on the private Docker network with **no host ports**; local-dev exposure moves to an opt-in compose override. *(Today all three are published.)*
- [ ] **Datastore durability — RESOLVED: accept data loss [§6.17].** Self-hosted Postgres+Redis co-located, no managed tier, **no backups**. **The obligation this creates:** the UI + privacy notice must state that **data may be lost on restart** — do not ship a "your history is saved" promise the architecture cannot keep.
- [ ] **Key-rotation runbook (§7.7):** document the one-liner (rotate secret in Space Secrets → restart → all sessions invalidate). No schedule, no IR programme.
- [ ] Run the **Celery worker** as a co-located process in the Space container.
- [ ] **Denial-of-wallet gate (§7.5):** per-IP guest-session creation limit, **global daily LLM budget breaker** (degrade to "at capacity", don't exhaust the quota), bot check on guest creation.
- [ ] Parity checklist vs v1 (chat, PDP, **market requirements**, feedback) + smoke tests. *(v1's job-listing search is intentionally **not** at parity — §1.1 scope ruling.)*
- [ ] **Cut over**, then delete v1 (`app.py`, `output_parser.py`, old `frontend/` CRA, etc.).

**Exit criteria:** v2 live on HF Spaces at full parity + new features (including P11 observability/analytics wired
in and reporting real data); only the UI port is reachable; quota abuse is bounded; v1 removed.

---

## Sequencing summary

```
P0 Scaffolding ─▶ P1 Skeleton (stream + failover + 1 tool) ─▶ P2 Persistence ─▶ P3 Auth/guest
   ─▶ P4 Multi-agent ─▶ P5 Doc-intel/CV+OCR ─▶ [SEC] ─▶ P6 Market intel ─▶ P7 PDP
   ─▶ P8 Dashboard ─▶ P9 Personalization+Feedback ─▶ P10 Guardrails ─▶ P11 Observability+Analytics
   ─▶ 🛑 PRE-GO-LIVE REVIEW (blocking: owner + architect) ─▶ P12 Deploy
```

Foundation = **P0–P3** (skeleton, reliability, data, identity). Features = **P4–P9**. Hardening + ship = **P10–P12**.
Reliability (LLM failover) and async infra (Celery) land in the foundation so every feature inherits them. Guardrails are introduced minimally once the agent graph exists (P4) and *completed* in P10 — security isn't bolted on last, only finished there. Observability/analytics (P11) deliberately lands *before* the pre-go-live review, so that review inspects real telemetry rather than a promise of it.

---

## Security & privacy sequencing (the [SEC] block)

The app is **not live** (branch-only), so nothing here is a production hotfix. But these items are ordered by
**cost-to-unwind**, not by exposure — each gets more expensive the longer it waits, and two of them are
*entrenched by the very next phase*. **[SEC] runs between P5 and P6.**

| # | Item | Land it | Why then |
|---|---|---|---|
| **S1** | **SSRF guard** on all outbound fetches (§7.2) | **before P6** | The crawler today does `follow_redirects=True` with **no** scheme/IP validation. P6 crawls at scale — a latent hole becomes a live one, and by then it has 3 callers instead of 1. |
| **S2** | **Untrusted-content fencing** for documents (§7.3) | **before P6** | P5 already feeds CV/OCR text into the model context. P6 adds postings. Fix the contract before a second source depends on it. |
| **S3** | **Topic guardrail** — `OFF_TOPIC` refuse / `JOB_HUNTING` redirect (§7.4) | **with P6** | P6 *is* the boundary between "market requirements" and "job board". The guardrail is what keeps the scope ruling (§1.1) true in code. |
| **S4** | **BFF + httpOnly cookie**, drop `localStorage` (§7.2 / §6.13) | **before P8** | Every new authed surface (dashboard, memory panel) that assumes a Bearer-in-JS token makes the migration bigger. Do it while the authed surface is still chat + profile. |
| **S5** | **Compose port lockdown** (§7.2) | **anytime — trivial** | Postgres, Redis and FastAPI currently publish host ports. One-line-per-service change, zero risk. |
| **S6** | **`DELETE /api/me` + `GET /api/me/export`** (§7.6) | **before P8/P9** | Erasure must cascade every store. Cheap with 8 tables; painful once dashboard + memories + PDPs reference `users`. |
| **S7** | **PII redaction + Art. 9 exclusion** in the memory writer (§7.6) | **with P9** | It's the phase that creates durable memories — the filter must exist *before* the first one is written. |
| **S8** | **Real injection classifier** replacing the regex deny-list (§7.4) | **P10** | The P4 heuristic is an honest placeholder; P10 is where it was always meant to be replaced. |
| **S9** | **Denial-of-wallet**: per-IP guest limits + global budget breaker + bot check (§7.5) | **P12 (go-live gate)** | Only matters when there's a public URL — but it *must* gate the launch, not follow it. |
| **S10** | **Contact-detail redaction at the LLM egress boundary** (§6.16 / §7.6) — name, email, phone, address, links, photo; keep employers/titles/dates/skills | **before P12** | One place (the LLM layer), not scattered across agents. |
| **S11** | **Log/trace PII redaction + retention** (§7.6) | **P11 (dedicated observability phase)** | Observability is where privacy programs die: traces would otherwise hold full CV text. Now lands with the OTel/telemetry work itself, not bolted on at cutover. |
| **S12** | ~~Datastore durability~~ → **RESOLVED: accept data loss** (§6.17) | — | Free app, ephemeral Space, no managed tier, no backups. **The obligation this creates is honesty:** UI + privacy notice must say data may be lost on restart. |
| **S13** | **Consent gate** — ToS/privacy checkbox at SSO login (recorded w/ policy version) and at **every** guest-session start (§6.22 / §7.6) | **with S4 (BFF)** | Session creation is the natural chokepoint, and S4 is already rewriting it. |
| **S14** | **Retention purge job** — SSO 30 days after last activity; guests session-only (§6.18) | **P9-ish** | Needs the durable stores to exist first; a periodic Celery task. |
| **S15** | **Error notification** — Sentry free tier, PII scrubbing on, low-noise alerts (§7.7 / §6.24) | **P11 (dedicated observability phase)** | The app's real failure mode is *silently broken and nobody notices*; bundled with the rest of telemetry rather than tacked onto cutover. |
| **S16** | **Key rotation runbook** — a documented **one-liner** (change secret → restart → sessions invalidate), not a process (§7.7) | **P12** | Right-sized: no rotation schedule, no IR programme. |

---

## Cost posture (budget-constrained — prefer free / OSS / self-hosted)

Everything is chosen to run at **zero or near-zero cost** (design §11):
- **LLM [decided]:** HF Inference free allowance; failover **`zai-org/GLM-5.2` → `Qwen/Qwen3.6-27B`** (both free OSS) doubles as the budget strategy — **no paid last-resort**.
- **Embeddings [decided]:** **`Qwen/Qwen3-Embedding-8B` via `sentence-transformers` in-process** (free, no API) — sets pgvector to **`vector(4096)`** — instead of a paid embedding endpoint.
- **Auth:** **backend SSO** (Authlib + Google/LinkedIn OIDC) — free, no password storage, no extra service.
- **Datastores [decided]:** **Postgres + Redis only, self-hosted** via `docker-compose` (local) + co-located on Spaces — **no managed tier** for now. Postgres JSONB + pgvector absorbs Mongo's role; rationale is single-container simplicity, not cost (§4 / §11). Managed tier (Neon/Supabase + Upstash) is the escape hatch if Spaces persistence is required.
- **Teachable memory [decided]:** **LangMem** in-process over the pgvector `user_memories` store — no external memory service (§6.7).
- **Doc-intel/OCR, guardrails, Celery, crawler:** all OSS/self-hosted (docling, Tesseract, Llama-Guard/regex, Celery, crawl4ai/playwright).
- **Observability/analytics [decided, §6.26–27]:** **OpenTelemetry** (OSS, vendor-neutral) exported to a free-tier OTLP backend + **Sentry free tier** (errors) + **Google Analytics 4** (engagement) — no paid APM/analytics tier, no bespoke in-app telemetry dashboard.

## Decisions locked before P1 (was: open items)

All pre-work decisions are now **locked** (see design §6 / CLAUDE.md). One item remains open (8).

1. **Orchestration → LangGraph** [DECIDED] (hand-rolled orchestrator rejected).
2. **Primary tool-calling model → `zai-org/GLM-5.2`** via HF Inference Providers (OpenAI-compatible) [DECIDED]. **Embedding model → `Qwen/Qwen3-Embedding-8B`**, in-process `sentence-transformers`, **output dimension 4096 → pgvector `vector(4096)`** [DECIDED].
3. **Datastores → Postgres + Redis only, self-hosted** [DECIDED]. Mongo consolidated into Postgres JSONB; **no managed tiers** (Neon/Supabase/Upstash) for now — `docker-compose` locally + co-located on Spaces.
4. **LLM failover → secondary `Qwen/Qwen3.6-27B`, no paid last-resort** [DECIDED]. **Guest rate-limit → 10 messages + 1 document upload per guest session** [DECIDED].
5. **Mid-stream failover → resume** (continue the in-flight stream on the secondary model, not restart-with-notice) [DECIDED].
6. **Teachable memory → LangMem** (in-process, over the pgvector `user_memories` store) [DECIDED] — supersedes the earlier "custom pgvector" choice; natural fit with LangGraph, avoids custom recall/learn, no external service (design §6.7).
7. **Learned-memory application (silent vs require confirmation) → TBD / OPEN** — to be decided in **P9** (design §5.4 / §6.7).
