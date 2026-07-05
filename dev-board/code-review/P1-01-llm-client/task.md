# Task P1-01-llm-client — LLMClient interface + HF OpenAI-compatible implementation
- **Phase:** P1   **Status:** ENG   **Tags:** (B)

## Scope
Implement `backend/app/llm/client.py`:
- Define an `LLMClient` interface (ABC/Protocol) that the rest of the app (router, agents) will depend on —
  not on any concrete provider SDK.
- Implement a concrete HF Inference Providers client using the **OpenAI-compatible** API surface (HF Inference
  Providers exposes an OpenAI-compatible chat-completions endpoint; use the `openai` Python SDK pointed at the
  HF base URL, or `huggingface_hub.InferenceClient` with OpenAI-compatible chat completions — pick whichever
  cleanly supports **native tool-calling** and **streaming**).
- Must support:
  - Chat completion with **native tool-calling** (`tools=[...]` JSON-schema style, tool_choice, receiving
    `tool_calls` back) — **no ReAct text parsing, no output_parser.py equivalent**.
  - **Token streaming** (async generator of chunks/deltas), including streaming tool-call deltas if the
    provider supports it.
  - Config-driven model id (this task only needs to support the primary model
    `zai-org/GLM-5.2`; the multi-model failover list is P1-02's `llm/router.py`, not this task).
  - Timeouts configurable per call.
- This is a single-provider client only. Do NOT implement failover/circuit-breaker logic here — that is
  `llm/router.py` (next task, P1-02) which will wrap one-or-more `LLMClient` instances.
- Wire config (API base URL, token, model id, default timeout) through `app/config.py`
  (`pydantic-settings`) — no hardcoded secrets, read from env / HF Space secrets.
- Add focused unit tests under `backend/tests/` using a mocked HTTP layer (do not hit the real HF endpoint in
  tests) covering: plain completion, tool-call round trip, streaming, and timeout behavior.

## Acceptance criteria
- [ ] `LLMClient` is an interface (ABC/Protocol) with a concrete `HFOpenAICompatibleClient` (or similarly named)
      implementation — callers depend on the interface, not the concrete class.
- [ ] Native tool-calling works end-to-end (schema in, `tool_calls` out) with no regex/text parsing of a ReAct
      format anywhere in this module.
- [ ] Streaming is implemented as an async generator yielding incremental content (and tool-call deltas if
      applicable).
- [ ] Config (base URL / token / model id / timeout) comes from `app/config.py`, not hardcoded.
- [ ] Unit tests pass with mocked HTTP; no real network calls in CI.
- [ ] `ruff` + `mypy` clean (project CI gates from P0).

## Design references
- dev-board/plan.md: P1 — Walking skeleton
- dev-board/app-design-and-features.md: §6 item 6 (primary LLM, native tool-calling, deletes ReAct parser),
  §6.6 (LLM failover router — router itself is out of scope here, but `LLMClient` must be the clean unit the
  router wraps), §8 Target Project Structure (`backend/app/llm/client.py`)

## Constraints / non-goals
- No failover/circuit-breaker/retry-across-models logic (that's `llm/router.py`, P1-02).
- No tool implementations here (that's `backend/app/tools/`, P1-03) — only the client's ability to send tool
  schemas and receive tool-call responses.
- Do not touch legacy `legacy-code/` (v1 `output_parser.py` etc.) — v2 code is fully independent; the goal is
  simply that the new path never uses ReAct text parsing.
