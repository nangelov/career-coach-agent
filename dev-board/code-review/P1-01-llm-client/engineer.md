# Engineer report — P1-01-llm-client · Revision 1

## Summary
Implemented the `LLMClient` interface plus a concrete HF Inference Providers client
(`HFOpenAICompatibleClient`) over the **OpenAI-compatible** chat-completions surface,
using the `openai` async SDK. Supports **native tool-calling** (schema in →
`tool_calls` out, zero ReAct/regex text parsing) and **token streaming** as an async
generator of incremental deltas (content + tool-call fragments). Config (base URL /
token / model id / timeout) flows from `app/config.py`; secrets stay in env / Space
secrets. Provider SDK exceptions are translated into a small first-party error
hierarchy so the P1-02 router can branch on our types, not the SDK's. This is a
**single-provider** client only — no failover / retry-across-models / circuit-breaker
(that is `llm/router.py`, P1-02); the client defaults to `max_retries=0` so retry
policy lives solely in the router.

## Files changed
- `backend/app/llm/types.py` — new. Provider-agnostic models: `Role`, `FunctionCall`,
  `ToolCall`, `ChatMessage` (+ `.to_openai()` wire serialization), `CompletionResult`,
  `ToolCallDelta`, `StreamChunk`. These are the vocabulary the router/agents speak.
- `backend/app/llm/errors.py` — new. First-party exceptions: `LLMError` base +
  `LLMTimeoutError`, `LLMConnectionError`, `LLMResponseError` (with `status_code`),
  `LLMRateLimitError`. These map to the §6.6 router's failover/retry triggers.
- `backend/app/llm/client.py` — new. `LLMClient` ABC + `HFOpenAICompatibleClient`
  (`complete`, `stream`, `from_settings`, `aclose`); translates the `openai` SDK to/from
  the first-party models and errors.
- `backend/app/llm/__init__.py` — export the public LLM surface.
- `backend/tests/test_llm_client.py` — new. 4 unit tests over a mocked HTTP transport
  (no network): plain completion, tool-call round trip, streaming (content + tool
  deltas), timeout translation.
- `backend/pyproject.toml` — bumped `openai` floor `>=1.12.0` → `>=2.0.0` (the 2.x
  `omit` sentinel / typed params are what the client is written against).
- `.github/workflows/backend-ci.yml` — added `openai` to the curated CI install so
  mypy sees the SDK's real types and pytest can import the client (openai is a light
  HTTP SDK, not part of the heavy ML stack).

## Key decisions
- **`openai` async SDK against the HF base URL** (design §2 / §6 item 6) — gives native
  `tools[]`/`tool_calls` and SSE streaming for free, which is exactly what removes the
  v1 `output_parser.py`. No text/ReAct parsing exists in this module.
- **Interface-before-implementation** (plan.md §"Interfaces before implementations"):
  callers depend on the `LLMClient` ABC + first-party models; the `openai` SDK is
  confined to `client.py`. One client instance = one model id, so the P1-02 router can
  hold an ordered list and wrap them (§6.6).
- **First-party error hierarchy** — SDK exceptions are translated in `_translate_error`
  (most-specific first: `APITimeoutError` before `APIConnectionError`, `RateLimitError`
  before `APIStatusError`). This is the clean seam the router needs to decide
  failover vs retry vs give-up without importing `openai`.
- **`max_retries=0` default** — retry/backoff and failover are the router's job (§6.6);
  keeping them out of the single client avoids double-retry and keeps policy in one place.
- **Timeouts** are per-call (`timeout=` arg) with a client default from
  `LLM_TIMEOUT_SECONDS`.
- **Testability via injected `http_client`** — `AsyncOpenAI(http_client=...)` takes an
  `httpx.AsyncClient` backed by `httpx.MockTransport`, so tests exercise the real SDK
  code path with zero network calls.
- **`omit` sentinel (openai 2.x)** — used instead of the legacy `NOT_GIVEN`; the 2.x
  `create()` signatures type optionals as `T | Omit`, and `stream=` is passed as a bool
  *literal* at each call site so mypy resolves the `ChatCompletion` vs `AsyncStream`
  overload correctly.

## How to verify
From `backend/` (openai + httpx present in the env — CI installs them in the curated step):
```bash
ruff check .
ruff format --check .
mypy app/
pytest -q
```
All four are green locally (see self-check). Tests hit only a mocked transport — no HF
endpoint is contacted.

## Self-check
- [x] Meets acceptance criteria:
  - `LLMClient` ABC + concrete `HFOpenAICompatibleClient`; callers depend on the interface.
  - Native tool-calling end-to-end (schema in → `tool_calls` out); no regex/ReAct parsing.
  - Streaming implemented as an async generator yielding content + tool-call deltas.
  - Config (base URL / token / model id / timeout) sourced from `app/config.py`.
  - Unit tests pass with mocked HTTP; no real network in CI.
  - `ruff` + `mypy --strict` clean.
- [x] No secrets committed; token/base-url read from settings (env / Space secrets).
- [x] Layering respected — interface-before-implementation; SDK isolated in `client.py`;
  no failover/router logic here (deferred to P1-02).
- [x] Tests/lints pass — output:
  - `ruff check .` → `All checks passed!`
  - `ruff format --check .` → `26 files already formatted`
  - `mypy app/` → `Success: no issues found in 20 source files`
  - `pytest -q` → `5 passed`

## Notes for reviewers
- Tool *definitions/implementations* are out of scope (P1-03, `app/tools/`); this client
  only ferries JSON-schema tool dicts and returns parsed `tool_calls`.
- `omit` requires `openai>=2.0`; floor bumped accordingly (no `uv.lock` is committed, so
  CI resolves latest — verified against openai 2.44).
