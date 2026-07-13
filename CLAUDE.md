# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⚠️ A v2 refactor is planned — read the design docs first

The code currently in the repo is **v1** (described below and still the running app). A ground-up **v2 refactor** has been designed but **not yet implemented**. Before doing substantial work, read:
- **[dev-board/app-design-and-features.md](./dev-board/app-design-and-features.md)** — v2 system design, architecture, tech stack, data model, features, security.
- **[dev-board/plan.md](./dev-board/plan.md)** — phased execution plan (P0–P12, foundation-first).

**Locked v2 decisions** (all 9 pre-work decisions are now locked except one — see below and the "Decisions locked before P1" list in `dev-board/plan.md`):
- **Orchestration → LangGraph** (confirmed; hand-rolled orchestrator rejected). Multi-agent graph (planner → workers → responder) with typed shared state.
- **Primary LLM → `zai-org/GLM-5.2`** with **native tool-calling** via HF Inference Providers (OpenAI-compatible) — this *deletes* the v1 ReAct text-parser (`output_parser.py`).
- **LLM failover → secondary `Qwen/Qwen3.6-27B`, no paid last-resort**; on **mid-stream** failure the in-flight stream **resumes** on the secondary (not restart-with-notice).
- **Backend:** modular async **FastAPI**. **Frontend:** **Next.js (App Router)** replacing CRA. **Streaming** chat (SSE).
- **Auth:** **SSO-only (Google + LinkedIn) via Authlib OIDC, backend-owned session JWT, no passwords** (PKCE, minimal scopes, secrets in HF Space Secrets).
- **Datastores → Postgres (pgvector + JSONB) + Redis only, self-hosted** — *no MongoDB* (consolidated into Postgres) and **no managed tier** (Neon/Supabase/Upstash) for now: `docker-compose` locally + co-located on Spaces.
- **Embeddings → `Qwen/Qwen3-Embedding-8B`** run **in-process via `sentence-transformers`** (no API cost), **output dim 4096 → pgvector `vector(4096)`** (fixes all migrations).
- **Teachable per-user memory → LangMem** (in-process, over the pgvector `user_memories` store) + **per-message 👍/👎 feedback**; **Celery** (Redis broker) for async OCR/doc-intel/crawling; **multi-LLM failover router**; **budget = free/OSS/self-hosted throughout**.
- **Guest rate-limit → 10 messages + 1 document upload per guest session** (guests limited harder; Redis-enforced).
- v1's `run_python_code` REPL is **removed** in v2 (ACE risk).
- **Still open (1):** learned-memory application — applied *silently but viewable/deletable* vs *require user confirmation* — TBD, to be decided in **P9**.

The v1 description below stays accurate until v2 lands; when implementing v2, follow `dev-board/plan.md` and update this file as phases complete.

## v2 development workflow (multi-agent, file-based handoff)

v2 work is built one task at a time through an **orchestrator agent** that drives a subagent pipeline.

- **[dev-board/tasks.md](./dev-board/tasks.md)** — the actionable task breakdown (pre-work decisions + P0–P12), tagged (B)/(F)/(I)/(D)/(T).
- **[dev-board/code-review/](./dev-board/code-review/)** — per-task subfolders where agents pass files to each other (`task.md`, `engineer.md`, `code-review.md`, `architecture-review.md`). `queue.md` is the status board.
- **`agent-handoff` skill** (`.claude/skills/agent-handoff/SKILL.md`) — single source of truth for the pipeline steps, folder layout, file templates, and verdict gates.
- **Four agent types** (`.claude/agents/`):
  - **orchestrator** (blue) — picks tasks, writes briefs, dispatches the pipeline, routes on verdicts, marks tasks done. Invoke it directly with `[IMPLEMENTATION <task>]`, `[IMPLEMENTATION_NEXT_TASK]`, or `[CODE_REVIEW <scope>]`.
  - **fullstack-engineer** (green) — implements the task (model: sonnet).
  - **code-reviewer** (orange) — reviews after the engineer for correctness/security/quality (model: opus).
  - **system-architect** (purple) — verifies conformance to `dev-board/plan.md` + `dev-board/app-design-and-features.md` (model: opus).

  All agents have `memory: project` — a persistent directory (`.claude/agent-memory/<agent>/`) so they accumulate codebase conventions, recurring defect patterns, and design rulings across tasks.

**Pipeline (always):** orchestrator briefs → engineer implements → **code-reviewer AND system-architect run in parallel** → if either logs `CHANGES_REQUESTED`, engineer fixes → only flagged reviewer(s) re-verify → loop until both `APPROVED` → orchestrator checks off in `tasks.md`.

## Overview (v1 — current code)

AI career-coaching assistant: a LangChain ReAct agent backed by `meta-llama/Llama-3.3-70B-Instruct` (served via Hugging Face Inference), exposed through a FastAPI backend, with a React/TypeScript chat frontend. Deployed as a Docker image on Hugging Face Spaces (`app_port: 8000`).

## Commands

Backend (run from repo root):
```bash
pip install -r requirements.txt
python main.py                      # runs uvicorn on 0.0.0.0:8000 (entry point)
uvicorn main:app --reload           # dev with autoreload
```

Frontend (run from `frontend/`):
```bash
npm install
npm start                           # CRA dev server, proxies API to localhost:8000
npm run build                       # produces frontend/build/ — backend serves this in prod
npm test                            # react-scripts test (Jest); no backend test suite exists
```

Docker (builds frontend + backend into one image):
```bash
docker compose up --build           # serves the full app on :8000
```

There is **no Python test suite, linter, or formatter configured.** `npm test` is the only test runner, and there are no committed frontend tests.

## Required environment variables

Set in `.env` (read by `app.py` / tools at import time — missing values raise on startup):
- `HUGGINGFACEHUB_API_TOKEN` — required by `app.py`; also doubles as the auth `key` for the `GET /get-feedback` endpoint.
- `SERPAPI_API_KEY` — required by `tools/google_jobs_search.py` (Google Jobs search).
- `RAPID_API_KEY` — present in `.env`.

## Architecture

### Two agents, shared everything
`app.py` builds **two** LCEL ReAct agents that share the same `prompt`, `tools` list, and a single global `ConversationBufferMemory`:
- **`agent_executor`** — the conversational `/agent/query` agent. Uses `FlexibleOutputParser`, `max_new_tokens=1024`.
- **`pdp_agent_executor`** — the Personal Development Plan generator for `/pdp-generator`. Uses `PDPOutputParser`, `max_new_tokens=3072`, and clears memory before each run to avoid contamination.

Both bind `stop=["\nHuman:", "Human:", ...]` to suppress the LLM hallucinating the next turn, run with `max_iterations=5` and `handle_parsing_errors=True`.

The single shared module-level `memory` is global state across **all** requests (no real per-thread isolation). `thread_id` is cosmetic: a request with no `thread_id` clears memory entirely; `clear_memory_if_corrupted()` wipes memory when >20% of messages look corrupted (empty or containing `"Human:"`).

### Output parsing is the heart of this codebase
The Llama model does not reliably emit clean ReAct format, so `output_parser.py` does heavy defensive cleanup. **When changing prompt format or model, expect to touch the parser.** Key behaviors:
- `FlexibleOutputParser` — extends `ReActSingleInputOutputParser`. Handles: LLM emitting both `Action:` and `Final Answer:` (keeps Action only); `Action: None` (→ final answer); bare responses with no ReAct keywords (→ final answer); malformed ReAct via `_parse_malformed_react`; strips `<|eot_id|>` / `<|eom_id|>` / `<|...|>` special tokens; preserves job-search results verbatim.
- `clean_llm_response(output)` — applied to `/agent/query` output before returning; strips special tokens, everything after `Human:`, and extracts the last `Final Answer:`.
- `PDPOutputParser` — strips ReAct scaffolding and keeps only the `## Current Skills Assessment …` markdown sections.
- `validate_pdp_response(text)` — gate before PDF generation: requires ≥500 chars, ≥4 of 6 required section headings, and rejects leaked scaffolding (`Action:`, ```` ```python ````, `SyntaxError`, etc.).

The system prompt in `prompts.yaml` is tightly coupled to all of the above — it dictates the exact ReAct format, the "never emit both Action and Final Answer" rule, and job-search formatting rules the parser relies on.

### Tools (`tools/`)
Registered in `tools/__init__.py` and passed as the `tools` list in `app.py`. Each is a LangChain `@tool`. Adding a tool = create the module, export it from `__init__.py`, add it to the `tools` list (it's auto-rendered into the prompt via `render_text_description` + `tool_names`). `google_job_search` tries the LangChain `GoogleJobsAPIWrapper` first, then falls back to a direct `serpapi` call.

### PDP generation flow (`POST /pdp-generator`)
Multipart upload → temp PDF → `PyPDFLoader` + `RecursiveCharacterTextSplitter` extract CV text → a large structured prompt (with fixed `##` section headers) → `pdp_agent_executor` → `validate_pdp_response` → `helpers/create_pdp_pdf` renders a styled PDF via `reportlab` → returned as a `StreamingResponse`. The PDF section parsing in `helpers/helper.py` (`prepare_pdf_content`) does its own lightweight markdown→reportlab conversion; the section headers there must stay in sync with the prompt.

### Helpers (`helpers/`)
- `helper.py` — `clean_input` (tool-input sanitizer, used by tools) and the reportlab PDF builders.
- `feedback_handler.py` — `store_feedback` / `read_out_feedback`. Feedback is persisted as JSON files under **`/app/data/feedback/`** (the container path, with atomic temp-file + `.bak` writes), grouped one file per day.

### Frontend (`frontend/`)
Create-React-App + TypeScript + styled-components. `ChatBot.tsx` is the container managing messages, `threadId`, loading, and the PDP/feedback dialogs; it calls the backend via axios (CRA `proxy` → `localhost:8000` in dev). Google Analytics (`gtag`) is wired in. In production the backend serves `frontend/build/` and falls back all non-`agent/` routes to `index.html` (SPA routing) — see the bottom of `app.py`.

## API endpoints
- `POST /agent/query` — `{query, thread_id?, context?}` → conversational agent response + thought process.
- `POST /agent/cancel/{thread_id}` — cancels an in-flight request (tracked in `active_requests`).
- `POST /pdp-generator` — multipart: `file` (PDF), `career_goal`, `additional_context?`, `target_date` → streamed PDF.
- `POST /agent/feedback` — `contact`, `feedback` query params → stores feedback.
- `GET /get-feedback?key=<HF_TOKEN>` — dumps all feedback; authenticated by matching `HUGGINGFACEHUB_API_TOKEN`.
