# Engineer report — P1-03-tools · Revision 1

## Summary
Implemented `backend/app/tools/` as the **canonical native-tool pattern** the rest of the app will
follow. A tool is a self-contained unit that exports (a) a JSON-schema definition in the OpenAI
`tools[]` shape — the exact dict P1-01's `LLMClient` / P1-02's `LLMRouter` pass through to the HF
OpenAI-compatible endpoint — and (b) an async executor over the model's parsed arguments. A
`ToolRegistry` is the single wiring point: register a tool once and it can hand the collected
schemas to the LLM layer and dispatch a model-emitted `ToolCall` to the right executor, returning a
`role="tool"` `ChatMessage` tagged with the originating `tool_call_id`. Adding tool #3 later (P4+)
is "drop a module in `tools/`, register it in `registry.py`".

Two tools ship:
- **`current_date_and_time`** — trivial, no external I/O ("prove the plumbing" tool); returns the
  current date/time, optionally in a caller-supplied IANA timezone.
- **`internet_search`** — general web search over **SearXNG** (OSS, self-hostable, **no API key** —
  §11 budget posture), distinct from the P6 SerpAPI/Google-Jobs path. Results are treated as
  **untrusted external data**: only plain `title`/`url`/`snippet` strings are extracted and
  truncated; nothing is executed or interpreted as instructions.

Every failure mode (unknown tool, malformed argument JSON, non-object args, bad timezone, missing
`query`, unconfigured backend, HTTP error/timeout, or an exception raised inside an executor) returns
a **graceful error tool message**, never an unhandled exception into the caller.

## Files changed
- `backend/app/tools/base.py` — new. `ToolSchema` alias, `ToolResult` (`.ok`/`.error`/`.to_message`),
  `Tool` ABC (`name`, `schema`, async `run`), `ToolRegistry` (`register`/`get`/`names`/`schemas`/
  async `execute`), and `_parse_arguments` (raw `function.arguments` JSON → dict, graceful on bad input).
- `backend/app/tools/current_date_and_time.py` — new. `CurrentDateTimeTool`.
- `backend/app/tools/internet_search.py` — new. `InternetSearchTool` (+ `from_settings`, injectable
  `httpx.AsyncClient`, result cap/snippet-truncation helpers).
- `backend/app/tools/registry.py` — new. `build_default_registry()` — the one place tools are wired.
- `backend/app/tools/__init__.py` — export the public surface.
- `backend/app/config.py` — added `SEARXNG_URL` (default `""`) and `SEARCH_TIMEOUT_SECONDS` (default 10.0).
- `backend/tests/test_tools.py` — new. 19 tests (schema shape, tool execution, graceful errors,
  registry round trip); all `internet_search` HTTP served by `httpx.MockTransport` — no network.

No changes to `llm/*` — the tools plug into the existing `ChatMessage`/`ToolCall`/`FunctionCall`
vocabulary unchanged. No CI change: the tools add **no new dependency** (SearXNG is called over
`httpx`, already installed in the curated CI step via the dev group + `openai`).

## Key decisions
- **Registry-as-single-wiring-point** (task "drop a module in `tools/`, register it"): tools own their
  own config/clients; `ToolRegistry.execute(ToolCall) -> ChatMessage` performs the whole round trip
  (parse args → dispatch → build tool message), so a caller (P1-04's `/api/chat` loop) never has to
  re-implement argument parsing or error handling. `schemas()` returns the list for `tools=`.
- **`ToolResult.content` is always a JSON string** so it drops straight into a `role="tool"`
  `ChatMessage`; `is_error` marks graceful failures without changing the message shape the model sees.
- **SearXNG as the search backend** (design §11): OSS + self-hostable (mirrors the self-hosted
  Postgres/Redis posture) + **no API key** + clean JSON. Instance URL comes from `settings.SEARXNG_URL`
  (never hard-coded); when unset the tool returns a graceful "not configured" result rather than
  failing — it stays inert until an operator points it at an instance (e.g. `http://searxng:8080`).
  This is deliberately separate from the P6 job-search SerpAPI/Google-Jobs path (§11 "keep SerpAPI
  free tier" is a later, distinct concern).
- **Untrusted-data handling**: search results are reduced to `{title, url, snippet}` plain strings,
  snippets truncated to 400 chars, result count clamped to `[1, 10]`. No result text is executed or
  surfaced as instructions (full guardrails are P10; this just avoids anything unsafe now).
- **Testability via injected `httpx.AsyncClient`** — `InternetSearchTool` and `build_default_registry`
  accept a client backed by `httpx.MockTransport`, so tests exercise the real request/response path
  with zero network (consistent with the P1-01 MockTransport convention).
- **`ToolSchema` defined locally** in `tools/base.py` (structurally identical `dict[str, Any]` to
  `llm.client.ToolSchema`) so `tools/` carries no import dependency on `client.py` (and thus no
  transitive `openai` import) — the schemas are just dicts and drop into the client's `tools=` param.

## How to verify
From `backend/` (openai + httpx present in the curated env):
```bash
.venv/bin/ruff check app/tools tests/test_tools.py app/config.py
.venv/bin/ruff format --check .
.venv/bin/mypy app/
.venv/bin/python -m pytest -q
```

**One round-trip example** (model requests tool → app executes → app appends tool message → model
continues) — the loop a caller (P1-04) will drive:
```python
from app.tools import build_default_registry
from app.llm.types import ChatMessage

registry = build_default_registry()                 # schemas + executors, wired
messages = [ChatMessage(role="user", content="What's the date in Sofia?")]

# 1) app gives the model the tool schemas:
result = await client.complete(messages, tools=registry.schemas())

# 2) model asked for a tool → app executes it and appends the assistant + tool messages:
if result.tool_calls:
    messages.append(ChatMessage(role="assistant", tool_calls=result.tool_calls))
    for call in result.tool_calls:
        messages.append(await registry.execute(call))   # -> role="tool" ChatMessage w/ tool_call_id

    # 3) model continues with the tool output in context:
    result = await client.complete(messages, tools=registry.schemas())
```
`registry.execute(call)` returns a `role="tool"` `ChatMessage` whose `tool_call_id` matches
`call.id` and whose `content` is the JSON tool output — ready to append and round-trip.

## Self-check
- [x] Meets acceptance criteria:
  - `current_date_and_time` + `internet_search` each have a JSON-schema definition + async executor,
    following one consistent registry pattern in `tools/`.
  - Executors take parsed args (from `tool_calls[].function.arguments`) and return a structured result
    that builds a `role="tool"` `ChatMessage` (via `ToolRegistry.execute` / `ToolResult.to_message`).
  - `internet_search` uses a free/OSS backend (SearXNG); URL from `app/config.py`, never hard-coded.
  - Bad input → graceful error payload (`ToolResult.error`), not an unhandled exception.
  - Unit tests pass with mocked HTTP (`httpx.MockTransport`); no real network in CI.
  - `ruff` + `mypy --strict` clean.
- [x] No secrets committed; `SEARXNG_URL`/timeout from settings (env / Space secrets).
- [x] Layering respected — interface-before-implementation (`Tool` ABC + `ToolRegistry`); tools plug
  into the existing `llm/types.py` vocabulary; no `/api/chat` endpoint or model-driven loop wiring
  (P1-04), no job-search SerpAPI (P6), no RAG/pgvector tools (P2/P4).
- [x] Tests/lints pass:
  - `ruff check` → `All checks passed!`
  - `ruff format --check .` → `33 files already formatted`
  - `mypy app/` → `Success: no issues found in 25 source files`
  - `pytest -q` → `34 passed` (15 prior + 19 new)

## Notes for reviewers
- `internet_search` is intentionally **inert until configured** (`SEARXNG_URL` empty ⇒ graceful
  "not configured" result). This keeps P1 dependency-free and lets an operator/docker-compose point
  it at a self-hosted SearXNG later; wiring an actual instance is deployment config, not code.
- Added no new package: SearXNG is queried over `httpx` (already a dependency), so the CI curated
  install is unchanged.
