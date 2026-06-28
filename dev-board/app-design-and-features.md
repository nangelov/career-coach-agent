# Career Coach Agent — App Design, Architecture & Tech Stack

> Design document for the v2 refactor. Companion to [plan.md](./plan.md).
> Status: **Proposed** · Owner: Nikolay Angelov · Last updated: 2026-06-28 (all 9 pre-work decisions locked; only learned-memory application open)

---

## 1. Goals & Motivation

The v1 app is a single-file FastAPI server driving a LangChain **ReAct text-agent** against `meta-llama/Llama-3.3-70B-Instruct`. Because the model doesn't reliably emit clean tool calls, ~450 lines of `output_parser.py` exist purely to repair malformed output. Conversation state is a **single global `ConversationBufferMemory` shared across all requests**, so there is no real per-user or per-session isolation. Persistence is day-bucketed JSON files. The frontend is Create-React-App (deprecated).

**v2 goals:**

1. Replace fragile ReAct text-parsing with **native tool-calling** on an OSS model.
2. Move from one monolithic agent to a **multi-agent orchestration** (planner → workers → responder).
3. Real **per-session state** with proper persistence — **budget plan: Postgres (pgvector + JSONB) + Redis** (Mongo consolidated away; see §4 / §11).
4. **Accounts + guest mode**, saved history, reusable CV/profile.
5. **Streaming** chat UX on a modern **Next.js** frontend.
6. **Security guardrails**: jailbreak / prompt-injection protection on input and output.

**Non-goals (v2):** mobile apps, multi-tenant org/team features, payment/billing, fine-tuning our own model.

---

## 2. Tech Stack

| Layer | v1 (current) | v2 (target) |
|---|---|---|
| LLM | Llama-3.3-70B via HF `text-generation` (no tool calls) | **`zai-org/GLM-5.2`** (primary) with **native tool-calling** via HF Inference Providers (OpenAI-compatible endpoint) [DECIDED §6] |
| LLM reliability | single endpoint, no fallback | **Multi-LLM failover router** — primary `zai-org/GLM-5.2` → secondary **`Qwen/Qwen3.6-27B`**; timeout/health-aware, **no paid last-resort** (see §6.6) |
| Personalization | none | **Teachable per-user memory** — learns preferences & communication style, retrieved into context each turn (see §5.4) |
| Feedback signal | free-text form only | Free-text form **+ per-message thumb up/down / approve-disapprove** feeding the learning loop (see §5.5) |
| Background jobs | none (sync, in-request) | **Celery** (Redis broker) — async OCR / document processing / web crawling |
| Agent framework | LangChain ReAct + custom parser | **LangGraph** multi-agent state graph (model-agnostic, runs on HF) — *see §6 decision* |
| Backend | FastAPI (single `app.py`) | **FastAPI**, modular (routers / services / agents / repositories), fully async |
| Frontend | React 18 (CRA) + styled-components | **Next.js (App Router) + React + TypeScript**, streaming UI |
| Vector store / RAG + memory | none | **Postgres + pgvector** (RAG KB, teachable memory) |
| Embeddings | none | **`Qwen/Qwen3-Embedding-8B`** in-process via `sentence-transformers` — **4096-dim** output, fixes pgvector `vector(4096)` column size [DECIDED §6] |
| User / session / document store | JSON files | **Postgres (JSONB)** — consolidated; replaces a separate MongoDB (§4 / §11) |
| Cache / ephemeral / broker | none | **Redis** (session cache, streaming state, Celery broker, rate limits) |
| Auth | none | Guest sessions + **SSO (Google + LinkedIn, OIDC), backend-owned session** (FastAPI + Authlib, no passwords stored) — *see §6.2* |
| CV ingestion | `PyPDFLoader` (text PDFs only) | **Document-intelligence pipeline with OCR** (handles scanned / image / slide-style CVs) — see §5.1 |
| PDF (output) | reportlab | reportlab (kept) |
| Deploy | HF Spaces (single Docker) | **HF Spaces** Docker; **self-hosted Postgres + Redis** (co-located containers; no managed tier for now — §11) |

### OSS models (must support tool/function calling) [DECIDED §6]
- **Primary: `zai-org/GLM-5.2`** — native tool/function-calling via HF Inference Providers (OpenAI-compatible).
- **Secondary / failover: `Qwen/Qwen3.6-27B`** — used by the §6.6 router when the primary is slow/down; **no paid last-resort**.
- Earlier candidates (`meta-llama/Llama-3.3-70B-Instruct`, `Qwen/Qwen2.5-72B-Instruct`, Mistral family) are superseded by the locked choice above but remain swappable behind `LLMClient`.

Access them through HF Inference Providers' **OpenAI-compatible** API so the client (`openai` SDK or `huggingface_hub.InferenceClient`) handles `tools=[...]` / `tool_calls` natively — this is what removes `output_parser.py`. The model is configured in one place behind an `LLMClient` interface so it can be swapped — and that interface is also where **failover** lives (§6.6): an ordered list of models/providers tried with per-call timeouts and health tracking, so a slow or unresponsive endpoint transparently falls back to the next.

---

## 3. System Architecture

```
                         ┌─────────────────────────────────────────────┐
                         │              Next.js Frontend                │
                         │  Chat (SSE stream) · Auth · CV upload · PDP  │
                         └───────────────┬─────────────────────────────┘
                                         │  HTTPS / SSE
                         ┌───────────────▼─────────────────────────────┐
                         │            FastAPI  (async)                  │
                         │  Routers → Services → Agent Orchestrator     │
                         │  Guardrails (in/out) · Auth · Rate limit     │
                         │  LLM failover router (§6.6)                  │
                         └─────────┬──────────────┬──────────┬─┘
                                   │              │          │ enqueue
                  ┌────────────────▼──┐ ┌─────────▼──┐ ┌─────▼────────┐
                  │   Postgres        │ │   Redis    │ │ Celery worker│
                  │ users·sessions·   │ │ cache,     │ │ (Redis broker)│
                  │ history·feedback  │ │ stream,    │ │ OCR · doc    │
                  │ (JSONB) +pgvector │ │ broker,    │ │ parse · crawl│
                  │ RAG·memory·jobs·  │ │ limits     │ │ (async)      │
                  │ PDP·dashboard     │ │            │ │              │
                  └───────────────────┘ └────────────┘ └──────┬───────┘
                            │                                    │
                  ┌──────────▼──────────────────────────────────────┐
                  │  External tools: HF Inference (LLM + embeddings),│
                  │  job search APIs (SerpAPI/Google Jobs),          │
                  │  web crawler (job profiles), Wikipedia           │
                  └──────────────────────────────────────────────────┘
```

### Multi-agent orchestration (the core of v2)

A **graph of specialized agents** coordinated by a planner. Each node uses native tool-calling; the orchestrator carries typed shared state.

```
            ┌──────────────┐
  user ───▶ │  Guardrails  │  input safety: jailbreak / prompt-injection / PII scan
            └──────┬───────┘
                   ▼
            ┌──────────────┐
            │ Memory recall│  fetch user prefs + learned memories (§5.4) into context
            └──────┬───────┘
                   ▼
            ┌──────────────┐
            │   Planner    │  classify intent, decompose, route to workers, set budget
            └──────┬───────┘
        ┌──────────┼─────────────┬───────────────┐
        ▼          ▼             ▼               ▼
 ┌───────────┐ ┌─────────┐ ┌───────────┐  ┌──────────────┐
 │   RAG     │ │  Web    │ │   Job     │  │  PDP /        │
 │  Agent    │ │ Searcher│ │  Search   │  │  Resume Agent │
 │ (pgvector)│ │+ Crawler│ │  Agent    │  │              │
 └─────┬─────┘ └────┬────┘ └─────┬─────┘  └──────┬───────┘
       └────────────┴────────────┴───────────────┘
                          ▼
                 ┌─────────────────┐
                 │ Response Agent  │  synthesize, cite sources, format
                 └────────┬────────┘
                          ▼
                 ┌─────────────────┐
                 │   Guardrails    │  output safety: leak / injection-echo / policy
                 └────────┬────────┘
                          ▼  SSE stream to client
                          │
                 ┌────────▼────────┐
                 │ Memory writer   │  post-turn: extract durable prefs, apply thumb
                 │ (async, Celery) │  up/down signal → update user memories (§5.4–5.5)
                 └─────────────────┘
```

**Agents / nodes:**
- **Planner** — classifies intent (chat / job search / PDP / CV question / smalltalk), decomposes into steps, decides which workers run and in what order, sets an iteration/token budget.
- **RAG Agent** — embeds the query, retrieves from pgvector KB (curated career/learning content + the user's parsed CV chunks), returns grounded snippets with citations.
- **Web Searcher + Crawler** — internet search and **crawls job-profile / role pages** to extract structured info (skills, requirements). Writes findings to Postgres for reuse.
- **Job Search Agent** — queries job APIs (Google Jobs/SerpAPI + others), normalizes listings, optional **match scoring** against the user profile.
- **PDP / Resume Agent** — parses the CV into a structured profile, runs skills-gap analysis, produces the structured PDP that feeds the reportlab PDF builder.
- **Response Agent** — merges worker outputs into one coherent, cited answer; owns tone/formatting (**adapted to the user's learned communication style**); streams tokens.
- **Memory recall / writer** — recall pulls the user's structured preferences + top-k learned memories into context before planning; the writer (post-turn, async) extracts durable new preferences and folds in thumb up/down signal (§5.4–5.5).
- **Guardrails** (pre + post) — see §7.

State between nodes is a typed object (Pydantic) holding: user/session ids, message history slice, planner decisions, per-worker results, citations, and safety verdicts.

---

## 4. Data Model & Ownership

**Budget plan [DECIDED]: Postgres + Redis only** (no separate MongoDB). Postgres carries relational data, **pgvector** for embeddings, and **JSONB** for the document-shaped data Mongo would have held — one engine, fewer services, one free tier, simpler GDPR delete. The `repositories/` layer keeps this swappable, so adding Mongo later is possible but not planned (§11).

### Postgres — identity, conversation & documents (relational + JSONB)
- `users` — id, OIDC `provider` + `sub` (Google/LinkedIn), email, display name, created_at, `settings JSONB`. **No password hashes** (SSO-only).
- `profiles` — structured CV/profile per user (skills, experience, education, goals) as **JSONB**. Reused across chats (no re-upload).
- `preferences` — explicit per-user personalization settings (tone, formality, language, do/don't) as **JSONB**. User-editable. (§5.4)
- `sessions` — session id, user id (or `guest`), created/expires.
- `conversations` / `messages` — ordered messages (each with a stable `message_id`) + agent-trace metadata (JSONB). **Guests get NO persisted history** (session-scoped in Redis only).
- `message_feedback` — per-message reaction: `message_id`, user/session, `rating` (up/down / approve-disapprove), optional reason, timestamp. (§5.5)
- `feedback` — free-text product feedback; replaces the v1 JSON files.

### Postgres + pgvector — knowledge, memory & structured records
- `kb_documents` + `kb_chunks(embedding vector)` — RAG knowledge base (career resources, courses, role descriptions) and user-CV chunks for grounding.
- `user_memories(embedding vector)` — **teachable per-user memory** (§5.4): durable learned facts/preferences (text, type, confidence, source message, created_at), retrieved by similarity each turn. User-scoped and user-viewable/deletable.
- `jobs` — normalized job listings + crawled role profiles (dedup, cache, match scores).
- `pdps` — generated PDP records / metadata (PDF stored in object storage or regenerated on demand).
- **Dashboard (living PDP)** — relational, frequently-updated:
  - `goals` — user career goals (title, target role, target date, status).
  - `milestones` — checkpoints under a goal (due date, status).
  - `tasks` — actionable items (title, description, due date, status, source = user|ai).
  - `progress_entries` — append-only log of progress/notes/check-ins (for trend/streak views).
  - These are queried/mutated by both the user (UI) and the AI (see §5.2), so they live in Postgres for relational integrity and transactional updates.

**Connection pooling:** the `repositories/postgres.py` layer maintains a **single shared async connection pool** (SQLAlchemy `AsyncEngine`) — **max 5 connections** — shared across all requests and agents. Do not open per-request connections; acquire from the pool via the repository layer only.

### Redis — ephemeral / hot path
- Active session working memory (recent turns, planner scratch) — including **guest sessions**.
- Streaming/cancellation state (replaces v1's in-process `active_requests` dict).
- Rate limiting (per ip/user/session) and tool-result caching (e.g. repeated job queries).
- Embedding / search result cache (TTL).

**Connection pooling:** the `repositories/redis.py` layer maintains a **single shared `ConnectionPool`** (`redis.asyncio`) — **max 10 connections** — shared across all requests and agents. Do not instantiate per-request `Redis()` clients; acquire via the repository layer only. (Celery manages its own Redis connections internally via `kombu` — separate from this pool.)

---

## 5. Feature Specs

| Feature | Behavior | Stores touched |
|---|---|---|
| **Guest login** | One-click anonymous session; full chat + job search + PDP; **no history saved** (Redis only, TTL). **Rate-limited to 10 messages + 1 document upload per guest session** [DECIDED §6]; exceeding either prompts upgrade. Upgrade-to-account preserves current session. | Redis |
| **Accounts + saved history** | **SSO login (Google/LinkedIn)**; conversations + profile persisted; resume past chats. | Postgres |
| **Streaming chat** | SSE token streaming, visible "thinking"/tool steps, stop button (Redis-backed cancel). Real per-session memory. | Redis, Postgres |
| **CV / resume handling** | Upload once (PDF/image/PPTX/DOCX) → **OCR + layout-aware document intelligence** (§5.1) → parsed to structured profile + embedded into pgvector → reused across chats; no re-upload per request. | Postgres (+pgvector) |
| **Richer job search** | Multi-source, filters (location/remote/salary), **web crawling of job/role profiles**, match scoring vs profile, save/track jobs. | Postgres, Redis |
| **PDP generator** | Same end product (styled PDF) but driven by structured profile + RAG-grounded recommendations; validated before render. Seeds the dashboard's goals/tasks. | Postgres |
| **Dashboard (living PDP)** | Goals, milestones, tasks, and progress tracking the user edits **and the AI can read/propose/update** (§5.2). Progress charts/streaks. The PDP becomes a living plan, not just a one-shot PDF. | Postgres |
| **Async processing** | Slow work (OCR/doc parse, web crawling) runs as **Celery** background jobs with progress surfaced to the UI; chat stays responsive. | Redis (broker), Postgres |
| **LLM failover** | If a model is slow/unresponsive, the request transparently falls back to the next model/provider (§6.6). | — |
| **Personalization (teachable)** | Learns each user's preferences & communication style over time; recalled into every turn so responses adapt. User can view/edit/delete what's learned. (§5.4) | Postgres (pgvector memories + JSONB prefs) |
| **Response feedback** | Per-message **thumb up/down / approve-disapprove** (+ optional reason); strong signal into the learning loop and analytics. (§5.5) | Postgres |
| **Guardrails** | Input + output safety on every turn (see §7). | Redis (cache verdicts) |

---

### 5.1 Document Intelligence & OCR (CV ingestion)

v1 used `PyPDFLoader`, which only extracts a text layer — **scanned CVs, image-only PDFs, and slide/presentation-style CVs (PPTX, image-heavy layouts) return little or nothing.** v2 needs a real document-intelligence pipeline: detect whether a document has a usable text layer, fall back to **OCR** when it doesn't, and recover **layout/structure** (columns, sections, tables) before parsing into the structured profile.

**Pipeline:**
```
upload (PDF / image / PPTX / DOCX)
   → type detect
   → has text layer?  ── yes ──▶ direct text extract (pypdf / python-docx / python-pptx)
                       └─ no  ──▶ rasterize → OCR + layout analysis
   → layout-aware structuring (sections, tables, reading order)
   → LLM-assisted parse → structured profile (skills, experience, education, goals)
   → embed chunks → pgvector;  profile JSONB → Postgres
```

**Open-source Document Intelligence alternatives** (to Azure AI Document Intelligence / AWS Textract / Google Document AI). Recommended tiering:

| Tier | Tool | Strengths | Notes |
|---|---|---|---|
| **Recommended primary** | **docling** (IBM, MIT) | PDF/DOCX/PPTX/images → structured Markdown/JSON, layout + table + reading-order, built-in OCR backends | Modern, actively maintained, single library covers most CV formats — best fit |
| Strong alternative | **Marker** | High-quality PDF→Markdown, good on complex layouts | PDF-focused; pairs with an OCR engine |
| Layout/OCR engine | **PaddleOCR (PP-Structure)** | Detection + recognition + layout/table structure, many languages | Heavier deps; great accuracy |
| Lightweight OCR | **Tesseract** (`pytesseract`) + **OCRmyPDF** | Ubiquitous, simple, adds a text layer to scanned PDFs | Baseline accuracy; good cheap fallback |
| Modern OCR | **Surya** | SOTA detection/recognition, 90+ languages, reading order | Newer; can back Marker |
| VLM-based | **OCR via a vision-language model** (e.g. Qw-VL / similar on HF) | Robust on messy slide-style CVs; can parse directly to JSON | Higher latency/cost; good last-resort for hard docs |

**Recommendation:** **docling as the primary engine** (covers PDF/DOCX/PPTX/images + OCR + layout in one dependency), with **Tesseract/OCRmyPDF** as a light fallback and a **VLM OCR path** reserved for documents that fail structured extraction. Wrap all of this behind a single `DocumentParser` interface in `backend/app/ingestion/` so engines can be swapped without touching the agents. OCR runs as a **Celery background job** (it can be slow) with progress surfaced to the UI (§5.3).

### 5.2 Dashboard — the living Personal Development Plan

The v1 PDP is a one-shot PDF. v2 turns it into a **living, trackable plan** the user works against over time, with the AI as a collaborator.

- **Entities** (Postgres, §4): `goals` → `milestones` → `tasks`, plus an append-only `progress_entries` log.
- **User actions (UI):** create/edit/complete goals, milestones, and tasks; log progress; view progress charts, streaks, and % completion toward each goal/target date.
- **AI participation — the dashboard is a set of native tools** the agents can call (read + write), so the assistant can:
  - propose goals/tasks from a generated PDP or a chat ("add these 5 tasks to my plan"),
  - update status, suggest next actions, re-plan when the user falls behind or a target date slips,
  - summarize progress and surface blockers.
- **Safety:** all AI writes are **scoped to the authenticated user** and surfaced as **explicit, confirmable changes** (proposed → user approves) rather than silent mutations; every change is attributable (`source = user|ai`) and logged.
- **Guests:** dashboard requires an account (it's persistent). Guests can preview/generate a PDP but not save a living plan — an upgrade prompt converts it.

### 5.3 Background jobs (Celery)

Anything slow or external runs off the request path so chat/UI stays responsive:
- **Document intelligence / OCR** (§5.1) — parse uploaded CVs, embed into pgvector.
- **Web crawling** — fetch and extract job/role profiles (§6 / Job agent).
- Optionally: periodic refresh of saved job searches, embedding re-indexing.

**Broker/result backend = Redis** (already in the stack). Jobs emit progress (state in Redis) that the UI polls or receives via SSE. Agents that need slow work **enqueue a task and stream a "working…" state** instead of blocking the turn. Runs as a separate `worker` process in `docker-compose` and as a second process in the HF Spaces container (or a co-located worker).

### 5.4 Personalization — the teachable agent (per-user memory)

Inspired by AutoGen's *Teachable Agent*: the assistant **learns durable facts and preferences about each user** and recalls them on later turns, so it adapts tone, depth, language, and advice style instead of starting cold every time.

**Two complementary stores:**
- **Explicit preferences** (Postgres `preferences` JSONB) — structured, user-editable settings: tone (concise vs detailed), formality, language, focus areas, do/don't list. Authoritative; always injected.
- **Learned memories** (Postgres `user_memories`, **pgvector — internal/in-DB, no external service** [DECIDED]; recall/learn managed by **LangMem**, §6.7) — free-form facts the system infers: "prefers bullet points", "targeting product management in fintech", "dislikes generic advice", "based in Berlin". Embedded and retrieved by similarity to the current turn.

**Loop (mirrors TeachableAgent's recall + learn):**
1. **Recall** (pre-turn, in graph): fetch explicit prefs + top-k relevant `user_memories` → inject into planner/responder context.
2. **Respond** adapted to that context.
3. **Learn** (post-turn, async via Celery): an extraction step proposes durable new memories from the exchange, **dedupes/updates** against existing ones (don't store transient chit-chat), and assigns confidence. **Thumb up/down (§5.5) is a strong signal** — a down-vote can demote/remove a memory or learn an explicit "don't do X".
4. **Transparency & control:** users can **view, edit, and delete** learned memories (a "What the coach knows about you" panel) — important for trust and GDPR. Explicit edits override inferred memories.

**Guests:** personalization is **session-only** (Redis, ephemeral) — nothing durable is learned without an account; upgrading persists it.

**Build vs library** — see decision §6.7. **Decided: LangMem** (in-process, over our pgvector `user_memories` store) — a natural fit with the locked LangGraph orchestrator that avoids hand-writing recall/learn/dedup while keeping the single-container constraint.

### 5.5 Response feedback (thumb up/down)

Per-message reactions, distinct from the v1 free-text form:
- Each assistant message carries a stable `message_id`; the UI shows **👍 / 👎 (approve / disapprove)** with an optional one-line reason.
- Stored in Postgres `message_feedback`; used for (a) the **personalization learning loop** (§5.4), (b) **analytics** (quality trends per intent/model — useful alongside the failover router to compare models), and (c) future evaluation datasets.
- A down-vote can trigger an inline "want me to try again?" regenerate, and nudges the memory writer to adjust.

## 6. Key Decisions (with recommendations)

1. **Orchestration framework → LangGraph. [DECIDED]** Model-agnostic, so it runs on HF OSS models; gives typed shared state, branching, retries, and streaming for the multi-agent graph. The hand-rolled async orchestrator alternative is rejected. (This also makes **LangMem** the natural teachable-memory fit — see §6.7.)
2. **Auth → SSO-only (Google + LinkedIn), backend-owned session. [DECIDED]** Two orthogonal axes resolved: *who owns the session* = **FastAPI** (where `users`/`sessions` already live), *how users prove identity* = **SSO** (no passwords). FastAPI runs the OIDC flow via **Authlib**, then mints its own short-lived session JWT; Next.js is a pure client sending it as a Bearer token. **Why SSO-only:** the app never sees users' Google/LinkedIn passwords (they authenticate on the provider's domain), so even a full Space compromise can't leak them — strictly safer than storing password hashes, and free. Login requests **minimal scopes only** (`openid email profile`). LinkedIn *profile import* (extra scopes + stored token) is a **separate opt-in feature**, not part of login. Security details in §7.1.
3. **Embeddings model → `Qwen/Qwen3-Embedding-8B`, in-process via `sentence-transformers`. [DECIDED]** Runs in the container (no API cost, §11) rather than a hosted endpoint. **Output dimension = 4096** (last-token pooling) → fixes the pgvector column at **`vector(4096)`** for `kb_chunks` and `user_memories` in all migrations. (The model supports Matryoshka truncation to smaller dims, but we standardize on the full 4096 unless a later migration explicitly changes it.)
4. **Object storage for PDFs** — store generated PDFs (e.g. S3-compatible / HF datasets) vs regenerate on demand. Recommendation: **regenerate on demand** in v2 to avoid another dependency.
5. **Datastores → Postgres + Redis only, self-hosted. [DECIDED]** No separate MongoDB; Postgres (pgvector + JSONB) absorbs its role (§4). **Both datastores are self-hosted** — Postgres(+pgvector) and Redis run as containers in `docker-compose` (local) and co-located in the HF Spaces container; **no managed tiers** (Neon/Supabase/Upstash) are used for now. Connection strings via Space secrets. Mongo remains addable later behind `repositories/` but is out of scope. (Managed tiers stay a future option if self-hosting on Spaces proves limiting — §11.)
6. **Primary LLM → `zai-org/GLM-5.2` via HF Inference Providers (OpenAI-compatible). [DECIDED]** Native tool/function-calling, so the v1 ReAct text-parser stays deleted. Configured behind `LLMClient`; the §6.6 router fails over to the secondary below.
7. **LLM failover → secondary `Qwen/Qwen3.6-27B`, no paid last-resort. [DECIDED]** Order: `zai-org/GLM-5.2` (primary) → `Qwen/Qwen3.6-27B` (secondary), both free OSS on HF Inference Providers. **No paid provider as a last failover entry.** Details in §6.6.
8. **Guest rate-limit policy → 10 messages + 1 document upload per guest session. [DECIDED]** Guests are limited harder than logged-in users (§4 / §5): a guest session (Redis-only, TTL) allows **at most 10 chat messages and 1 CV/document upload**; exceeding either prompts an upgrade-to-account. Enforced in Redis per session.
9. **Mid-stream failover behavior → resume. [DECIDED]** If the primary model fails *after* tokens have streamed, the in-flight stream **resumes on the secondary model** (continues the same response) rather than restarting with a "switching models" notice. See §6.6.
10. **Learned-memory application (silent vs confirm) → TBD / open.** Whether inferred memories are applied silently (but always viewable/deletable) or require explicit user confirmation before they take effect is **still open — to be decided in P9.** (§5.4 / §6.7)

### 6.6 LLM failover router (non-functional)

A single HF endpoint that is slow or down stalls the whole app. The `LLMClient` interface wraps an **ordered list of providers/models** and adds:
- **Failover order [DECIDED]:** primary **`zai-org/GLM-5.2`** → secondary **`Qwen/Qwen3.6-27B`** (both free OSS via HF Inference Providers). **No paid last-resort entry.** Both support native tool-calling so the agent loop is unaffected.
- **Per-call timeout** (and optionally a "first-token" deadline for streaming) → on breach, abort and try the next.
- **Health tracking / circuit-breaker** in Redis: temporarily skip an endpoint that recently errored or timed out; periodic recovery probes.
- **Retry/backoff** for transient 5xx/429, distinct from failover.
- **Mid-stream failover → resume [DECIDED]:** failover is clean before the first token; if the primary fails *after* tokens have streamed, the request **resumes on the secondary model** — continuing the same response rather than restarting with a "switching models" notice.
- Config-driven (model list, timeouts, order via env) so no code change to re-prioritize. Optionally a cheaper/faster model for the **planner** vs a stronger model for the **responder**.

### 6.7 Teachable memory — build vs library

**Decision: LangMem. [DECIDED — supersedes the earlier "custom on pgvector" choice]** Recall + learn are implemented with **LangMem** (LangChain's memory utilities) rather than a hand-written extraction/dedup step. **Rationale:** (1) **natural fit with LangGraph** (already the locked orchestrator, §6 item 1) — recall/learn slot into the graph without bespoke glue; (2) **avoids writing and maintaining our own recall/learn/dedup logic**, which the earlier decision flagged as the main risk ("if the custom extraction/dedup proves fiddly…"); (3) **still no external service** — using LangMem's **in-process** variant keeps the HF-Spaces single-container constraint intact and embeddings stay in-process (`Qwen/Qwen3-Embedding-8B`, §6 item 3). Memory vectors continue to live in our **pgvector** `user_memories` table where LangMem supports a pgvector-backed store, preserving user-scoped GDPR view/delete. The options table below is kept for historical context.

| Option | What | Trade-off |
|---|---|---|
| **LangMem** (LangChain) → **CHOSEN** | Memory utilities that fit LangGraph; in-process recall/learn over a (pgvector) store | Natural with the locked LangGraph orchestrator; no custom extraction/dedup to maintain; no external service in the in-process variant. Couples us to the LangChain ecosystem (acceptable — already adopted via LangGraph) |
| Custom on pgvector (*previous choice, now superseded*) | Our own recall + learn step over a `user_memories` table | Full control + one-call GDPR delete, but we own the extraction/dedup prompt and its upkeep — the effort LangMem removes |
| **mem0** (OSS) | Drop-in memory layer (extract/store/retrieve) | Fast to add, sensible defaults; another dependency + its own storage model to map onto ours |
| **Letta (MemGPT)** | Full agentic-memory framework | Powerful (self-editing memory) but heavy; more than we need and reshapes the architecture |
| **Zep** | Dedicated memory server + store | Strong recall/temporal features; adds a service to run/host (tension with HF Spaces single-container) |

If LangMem proves limiting, **mem0** or a custom pgvector step are fallbacks; Letta/Zep stay rejected (extra services fight the HF-Spaces single-container constraint).

*Remaining open question:* should learned memories require user confirmation before they're applied, or be applied silently but always viewable/deletable? **TBD / open — to be decided in P9.** *(Resolved since this doc's first draft: guest rate-limit = 10 messages + 1 doc per session; failover = free OSS only, no paid last-resort; mid-stream failure = resume — see §6 / §6.6.)*

---

## 7. Security & Guardrails

- **Input guardrails:** jailbreak / prompt-injection detection, off-topic/abuse filtering, PII scrubbing before content hits tools or external APIs. Crawled web content is treated as **untrusted** (never executed as instructions).
- **Output guardrails:** block system-prompt leakage, refuse policy-violating content, strip injected instructions echoed from crawled pages.
- **Tool isolation:** the v1 `run_python_code` REPL is **removed** (it was an arbitrary-code-execution risk and only did calculations). If math is needed, use a sandboxed/limited evaluator.
- **AuthZ:** users can only read their own conversations/profiles; the v1 `GET /get-feedback?key=<HF_TOKEN>` admin-via-LLM-token pattern is replaced with proper admin auth.
- **Secrets** via Space secrets / env only; never in code. Per-session and per-tool rate limits in Redis.

### 7.1 SSO / data-protection (decided auth model)

SSO-only (Google + LinkedIn) is chosen partly *because* it minimizes data-protection exposure on a public HF Space:

- **No user passwords ever touch the app** — users authenticate on Google/LinkedIn; we receive only an OIDC ID token. A full Space compromise **cannot leak Google/LinkedIn credentials** (they were never stored). This is strictly safer than email+password (no hashes to breach).
- **OAuth client secret + JWT signing key** live in **HF Space Secrets** (HF repos are often public — never commit them). Use **PKCE** so a leaked client ID alone isn't enough.
- **Minimal scopes** at login (`openid email profile`); **no refresh tokens stored** for login. LinkedIn *profile import* is a separate opt-in that would request extra scopes and a stored token — if added, the token is **encrypted at rest**, scoped narrowly, and revocable.
- **Redirect URIs locked** to the exact Space domain in the provider consoles (prevents token-redirect hijack).
- **Short-lived session JWTs** signed by the backend; rotate-able signing key. Stored user PII is minimal (`sub`, email, name) with GDPR view/delete (ties to §5.4 memory deletion).
- **Residual risk** is limited to *our* stored data (emails/profiles/tokens) — standard breach surface, mitigated by encryption-at-rest (managed tier or app-level) and minimal retention — **not** users' provider credentials.

---

## 8. Target Project Structure

```
career-coach-agent/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app factory, middleware, lifespan
│   │   ├── config.py                # pydantic-settings (env, secrets)
│   │   ├── api/                      # routers
│   │   │   ├── chat.py              # POST /chat (SSE stream), cancel
│   │   │   ├── pdp.py              # PDP generation
│   │   │   ├── jobs.py             # job search / save / track
│   │   │   ├── profile.py         # CV upload, profile read/update
│   │   │   ├── dashboard.py       # goals / milestones / tasks / progress
│   │   │   ├── auth.py            # guest + SSO (Google/LinkedIn OIDC via Authlib), session JWT
│   │   │   └── feedback.py
│   │   ├── agents/                  # multi-agent graph
│   │   │   ├── graph.py            # LangGraph wiring
│   │   │   ├── state.py           # shared typed state
│   │   │   ├── planner.py
│   │   │   ├── rag_agent.py
│   │   │   ├── web_searcher.py    # search + crawler
│   │   │   ├── job_agent.py
│   │   │   ├── pdp_agent.py
│   │   │   └── responder.py
│   │   ├── llm/
│   │   │   ├── client.py          # LLMClient interface (HF/OpenAI-compatible)
│   │   │   ├── router.py          # failover/timeout/health across models (§6.6)
│   │   │   └── embeddings.py
│   │   ├── tools/                   # native tool-call definitions (schemas + impls)
│   │   ├── ingestion/               # DocumentParser: type detect, OCR, layout, profile parse
│   │   ├── memory/                  # teachable memory: recall + learn/extract (§5.4)
│   │   ├── tasks/                   # Celery app + tasks (ocr/parse, crawl, memory-learn) + worker entry
│   │   ├── guardrails/              # input/output safety
│   │   ├── services/                # business logic (chat, pdp, jobs, profile)
│   │   ├── repositories/            # DB access (postgres / redis)
│   │   │   ├── postgres.py        # SQLAlchemy/SQLModel + JSONB + pgvector
│   │   │   └── redis.py
│   │   ├── pdf/                      # reportlab builders (from helpers/helper.py)
│   │   └── schemas/                 # pydantic request/response/domain models
│   ├── migrations/                  # alembic (postgres)
│   ├── tests/
│   ├── pyproject.toml               # uv/poetry; replaces requirements.txt
│   └── Dockerfile
├── frontend/                        # Next.js (App Router)
│   ├── app/                         # routes, layouts, streaming chat
│   ├── components/                  # chat, message, PDP dialog, feedback, auth
│   ├── lib/                         # api client (SSE), auth
│   └── package.json
├── docker-compose.yml               # local: app + worker + postgres + redis
├── Dockerfile                       # HF Spaces image (frontend build + backend)
├── app-design-and-features.md
├── plan.md
└── README.md
```

---

## 9. API Surface (v2)

| Method | Path | Purpose | Notes vs v1 |
|---|---|---|---|
| POST | `/api/chat` | Streaming chat (SSE) | replaces `/agent/query`; per-session memory |
| POST | `/api/chat/{session}/cancel` | Stop generation | Redis-backed (was in-process dict) |
| POST | `/api/profile/cv` | Upload + parse CV → profile | new; replaces re-upload-per-PDP |
| GET/PUT | `/api/profile` | Read/update structured profile | new |
| POST | `/api/pdp` | Generate PDP PDF | was `/pdp-generator`; uses stored profile |
| GET | `/api/dashboard` | Goals + milestones + tasks + progress summary | new (living PDP) |
| * | `/api/dashboard/goals\|tasks\|progress` | CRUD goals/tasks/progress entries | new; also exposed to AI as tools |
| GET | `/api/jobs/status/{task_id}` | Poll async job (OCR/crawl) progress | new (Celery) |
| GET/POST | `/api/jobs` | Search / save / track jobs | richer than v1 |
| POST | `/api/messages/{message_id}/feedback` | Thumb up/down + optional reason | new (per-message §5.5) |
| GET/PUT/DELETE | `/api/memory` | View / edit / delete learned memories + preferences | new (teachable §5.4) |
| POST | `/api/feedback` | Submit free-text feedback | was query-params → JSON body; stored in Postgres |
| POST | `/api/auth/guest` | Start guest session | new |
| GET | `/api/auth/login/{provider}` | Begin Google/LinkedIn OIDC (PKCE) | new (backend Authlib) |
| GET | `/api/auth/callback/{provider}` | OIDC callback → mint backend session JWT | new |
| POST | `/api/auth/logout` | End session | new |

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Self-hosted DBs not durable on an ephemeral Space | **Decided: self-host Postgres + Redis** (no managed tier for now, §11); documented escape hatch is switching connection strings to a managed tier (Neon/Supabase + Upstash) behind `repositories/` when persistence on Spaces is required |
| OSS model tool-calling quality varies | `LLMClient` abstraction + a model-swap matrix; keep a light schema-validation fallback (not the old parser) |
| Single LLM endpoint slow/down | **Failover router (§6.6)**: ordered models, per-call timeouts, Redis circuit-breaker |
| Long OCR / crawl blocks requests | **Celery** background jobs (§5.3); UI shows progress; agent streams "working…" |
| AI mutating dashboard incorrectly | AI writes are user-scoped, attributable (`source`), and confirmable (proposed → approved), not silent |
| Teachable memory drift / bad learning | Confidence scores, dedup/update on write, thumb-down demotes; user can view/edit/delete (§5.4); explicit prefs override |
| Privacy of learned user data | Memories user-scoped, viewable & deletable (GDPR); guests ephemeral; PII scrubbed before external calls |
| Multi-agent latency / cost | Planner sets budgets; Redis caches tool results & embeddings; stream early |
| Polyglot persistence complexity | Strict ownership (§4); repositories layer hides stores from services |
| Prompt injection via crawled pages | Treat web content as untrusted data; output guardrails; no tool-calls from crawled text |
| Scope creep | Phased delivery (see plan.md) — foundation first, features behind it |
| Cost / budget | Free-tier & OSS-first throughout (§11); failover across free LLM providers; in-process embeddings; optional consolidation onto Postgres |

---

## 11. Cost posture (budget-constrained)

Hard preference: **open-source, free, and self-hostable** wherever possible. Choices above are already cheap; this section makes the budget path explicit.

| Concern | Free / OSS path | Paid only if you opt in |
|---|---|---|
| **LLM inference** | HF Inference free allowance; failover **`zai-org/GLM-5.2` → `Qwen/Qwen3.6-27B`** (both free OSS) — the §6.6 router *is* the cost strategy; **no paid last-resort** [DECIDED] | (none — paid fallback explicitly declined) |
| **Embeddings** | **`Qwen/Qwen3-Embedding-8B` via `sentence-transformers` in-process** — runs in the container, no API cost; sets the pgvector dimension to **`vector(4096)`** [DECIDED] | Hosted embedding API |
| **Teachable memory** | **LangMem** in-process over the pgvector `user_memories` store — no external memory service [DECIDED §6.7] | Hosted memory service (mem0/Zep cloud) |
| **Auth** | **Backend SSO** (Authlib + Google/LinkedIn OIDC), free; no password storage | Clerk / hosted IdP (paid) |
| **Postgres + pgvector** (users/sessions/docs via JSONB + RAG/memory) | **Self-host in Docker** (`docker-compose` local + co-located on Spaces) — **no managed tier** [DECIDED] | Neon/Supabase managed tier (future option) |
| **Redis** | **Self-host in Docker** (broker + cache + limits) — **no managed tier** [DECIDED] | Upstash managed tier (future option) |
| **OCR / doc-intel** | docling, Tesseract, OCRmyPDF, PaddleOCR — all OSS | — |
| **Web crawling** | `crawl4ai` / Playwright (OSS) | Paid scraping API |
| **Guardrails** | Llama-Guard (OSS) or regex/heuristics | Hosted moderation API |
| **Job search** | Keep SerpAPI free tier; add OSS/free sources | More API quota |
| **Hosting** | HF Spaces free tier (single container; co-locate Celery worker) | Upgraded Space / VPS |

**Consolidated datastores [DECIDED]:** **Postgres + Redis only, self-hosted** — not a separate MongoDB, and **no managed tiers** (Neon/Supabase/Upstash) for now. Postgres covers everything stateful: **pgvector** for RAG + memories, **JSONB** for user/session/conversation/feedback documents (the role Mongo would play), and relational tables for jobs/PDP/dashboard. Redis stays for cache, streaming state, Celery broker, and rate limits. Both run as **self-hosted containers** via `docker-compose` locally and co-located in the HF Spaces container. *Rationale (not cost — Mongo CE/Atlas M0 are free too):* one engine beats two services to provision and monitor, and self-hosting avoids standing up external accounts during development. **Caveat (follow-up):** a HF Space is a **single, ephemeral container**, so self-hosted DBs there are not durable across restarts — when Spaces persistence is needed, switching the connection strings to a managed tier (Neon/Supabase + Upstash) is the documented escape hatch (kept behind `repositories/`, no service changes). The `repositories/` layer also keeps a future Mongo addition possible without touching services, but it's out of scope. See §4.

**Implication for §6.6 failover:** since free LLM tiers are rate-limited and occasionally down, the failover router isn't just reliability — it's how we stay free. Order the free providers; treat 429/timeouts as failover triggers; cache aggressively in Redis to conserve quota.
