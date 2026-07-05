# Task P1-03-tools — native tools: `current_date_and_time`, `internet_search`
- **Phase:** P1   **Status:** ENG   **Tags:** (B)

## Scope
Implement `backend/app/tools/` as the **canonical native-tool pattern** the rest of the app (P4 agents,
future job/RAG tools) will follow. Per `plan.md` line 39: 1–2 tools with proper JSON schemas.

Build:
- `tools/current_date_and_time` — trivial tool, no external deps: returns current UTC date/time (and
  accepts an optional timezone/format arg if you want to keep the schema realistic). This is the "just prove
  the plumbing works" tool.
- `tools/internet_search` — general web search (distinct from the job-search-specific SerpAPI/Google Jobs
  path that lands later in P6 — see design §11 "Job search: keep SerpAPI free tier"). Pick a **free/OSS**
  backend consistent with the budget posture (§11) — e.g. a free-tier search API or a no-key OSS option (your
  call; document the choice and any required env var in `engineer.md`). Treat search results as **untrusted
  external data** in how they're returned (plain structured snippets, not something a downstream prompt would
  execute as instructions — full guardrails land in P10, but don't do anything unsafe now).
- A small **tool registry** pattern: each tool exports (a) a JSON-schema `dict` compatible with the
  `tools=[...]` param the P1-01 `LLMClient`/P1-02 `LLMRouter` pass through to the HF OpenAI-compatible
  endpoint, and (b) an async callable that executes it given the model's parsed arguments. Structure this so
  adding tool #3 later (P4+) is "drop a module in `tools/`, register it" — no scattered wiring.
- Wire tool execution results back into the `ChatMessage`/`ToolCall` vocabulary from P1-01's `app/llm/types.py`
  (tool role message with `tool_call_id`) so a caller can round-trip: model requests tool → app executes →
  app appends tool result message → model continues. A short example of this loop belongs in
  `engineer.md`'s "how to verify" (doesn't need to be the full `/api/chat` endpoint — that's P1-04).
- Unit tests: schema shape is valid, each tool executes correctly on valid input, and handles bad/missing
  args gracefully (returns a tool-error payload rather than raising into the caller). Mock any external
  HTTP call in `internet_search`'s tests — no real network in CI.

## Acceptance criteria
- [ ] `current_date_and_time` and `internet_search` each have a JSON-schema tool definition + async executor,
      following one consistent registry pattern in `tools/`.
- [ ] Tool executors take parsed args (from a model's `tool_calls[].function.arguments`) and return a
      structured result usable to build a `tool` role `ChatMessage`.
- [ ] `internet_search` uses a free/OSS-tier backend; API key (if any) sourced from `app/config.py`, never
      hardcoded.
- [ ] Bad input to a tool executor returns a graceful error payload, not an unhandled exception.
- [ ] Unit tests pass with mocked HTTP; no real network calls in CI.
- [ ] `ruff` + `mypy` clean.

## Design references
- dev-board/plan.md: P1 line 39 ("Define 1–2 tools with proper JSON schemas... as the native-tool pattern")
- dev-board/app-design-and-features.md: §8 Target Project Structure (`backend/app/tools/`), §11 Cost posture
  (free/OSS/self-hosted by default; job-search-specific SerpAPI is a later, separate concern in P6)
- dev-board/code-review/P1-01-llm-client/engineer.md — `ChatMessage`, `ToolCall`, `FunctionCall` types this
  task's executors plug into
- dev-board/code-review/P1-02-llm-router/engineer.md — the router this tool loop will eventually run under
  (P1-04), for context only — no router changes needed here

## Constraints / non-goals
- No `POST /api/chat` endpoint or model-driven tool-call loop wiring here — that's P1-04. This task delivers
  the tools themselves plus a documented/testable "one round trip" example.
- No job-search-specific implementation (SerpAPI/Google Jobs) — that's P6's `agents/job_agent.py`.
- No RAG/pgvector-backed tools — that's P4/P2.
