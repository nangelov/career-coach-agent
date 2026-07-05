# Task P1-04-chat-endpoint — `POST /api/chat` SSE streaming + model-driven tool-call loop
- **Phase:** P1   **Status:** ENG   **Tags:** (B)

## Scope
Wire the first real end-to-end path (design §9: `POST /api/chat` — "Streaming chat (SSE); replaces
`/agent/query`"), built on the pieces already delivered this phase:
- `app/llm/router.py` — `LLMRouter` (P1-02), which wraps `app/llm/client.py`'s `LLMClient` (P1-01).
- `app/tools/registry.py` — `build_default_registry()` (P1-03): tool schemas + `ToolRegistry.execute()`.

This is **P1's "walking skeleton"** — plan.md Phase 1 explicitly says "no multi-agent yet". Do **not** build
`agents/graph.py`/LangGraph here (that's P4). The endpoint itself drives a simple **model-tool-call loop**:
send messages + tool schemas to the router → if the model returns `tool_calls`, execute them via the
registry, append the results, call the router again → repeat until the model returns a plain content
response → stream that content back over SSE. Cap iterations (reuse a sane default, e.g. 5, matching v1's
`max_iterations` spirit) to avoid infinite tool-call loops.

Respect the **Router → Service → Agent/Repository** layering (cross-cutting definition-of-done in
`tasks.md`): the FastAPI router (`app/api/chat.py`) should be thin — request/response + SSE plumbing — and
delegate the actual loop to a service (e.g. `app/services/chat.py`). The service owns the router/registry
call loop; no HTTP/SSE concerns leak into it.

**Session memory scope for this task:** full Redis-backed persistent session memory is the **next** task
(P1-05) — do not build it here. For this task, accept the conversation as part of the request (e.g. the
endpoint accepts a `session_id` plus the new `message`, and for now keeps/replays history in a simple
process-local structure, OR accepts the full message list in the request body — your call, but keep the
seam narrow so P1-05 can drop in a Redis-backed store behind the same interface without changing the
endpoint's public contract). Document the chosen interim shape clearly in `engineer.md` so P1-05 knows
exactly what to replace.

**message_id:** full "stable, feedback-ready" `message_id` semantics are P1-07's job, but since every
assistant message needs *some* identifier to stream sensibly, assign a simple UUID per assistant message now
and note in `engineer.md` that P1-07 will formalize/verify this.

Build:
- `app/services/chat.py` (or similar) — the tool-call loop service: takes conversation state + user message,
  calls `LLMRouter.stream()`/`.complete()` with `tools=registry.schemas()`, executes any `tool_calls` via
  `registry.execute()`, loops, and yields streamable events (content deltas, tool-call-started/finished
  events for UI visibility, final done event) — this event shape is what P1-08's Next.js page will consume.
- `app/api/chat.py` — `POST /api/chat` FastAPI router using `StreamingResponse`/SSE (`text/event-stream`),
  wired into `app/main.py`. Define a minimal request schema in `app/schemas/` (e.g. `ChatRequest`:
  `session_id`, `message`; optionally `history` for the interim in-memory approach).
- SSE event framing: pick a small, documented event vocabulary (e.g. `event: token`, `event: tool_call`,
  `event: tool_result`, `event: done`, `event: error`) — document it in `engineer.md` since the frontend
  (P1-08) depends on it.
- Failure handling: if the router exhausts all models (`LLMAllModelsFailedError` from P1-02), emit a
  terminal `error` SSE event and end the stream cleanly (no unhandled 500 mid-stream).
- Tests: a service-level test with a fake `LLMRouter`/registry double driving (a) a plain-answer path (no
  tool call), (b) a tool-call round trip (one tool call then a final answer), (c) iteration cap triggering,
  (d) router failure surfacing as a clean terminal error. An API-level smoke test (e.g. via FastAPI
  `TestClient`) that hits `/api/chat` and gets a valid SSE stream is a plus but not required if it's awkward
  with the app's current lifespan stubs — use judgement and note what you skipped and why.

## Acceptance criteria
- [ ] `POST /api/chat` streams tokens over SSE; a manual `curl`/httpx test against a running instance
      (documented in `engineer.md`) shows token-by-token output.
- [ ] The model can call a registered tool (e.g. `current_date_and_time`) mid-conversation, the loop executes
      it and continues, and the final streamed answer reflects the tool result.
- [ ] Router → Service → Agent/Repository layering respected: `app/api/chat.py` stays thin; the loop logic
      lives in `app/services/`.
- [ ] Iteration cap prevents runaway tool-call loops.
- [ ] All-models-failed is surfaced as a clean terminal SSE error, not an unhandled exception/500.
- [ ] Every assistant message carries some `message_id` (UUID is fine for now; full semantics in P1-07).
- [ ] Unit tests pass (fakes/doubles — no real HF network calls).
- [ ] `ruff` + `mypy` clean.

## Design references
- dev-board/plan.md: Phase 1 ("no multi-agent yet"; `POST /api/chat` with SSE streaming; tool-call loop
  driven by the model)
- dev-board/app-design-and-features.md: §9 API Surface (`POST /api/chat`), §8 Target Project Structure
  (`api/chat.py`, `services/`), §5.5 (message_id foundation, formalized in P1-07)
- dev-board/code-review/P1-01-llm-client/engineer.md — `LLMClient`/`ChatMessage`/`ToolCall` vocabulary
- dev-board/code-review/P1-02-llm-router/engineer.md — `LLMRouter.complete()`/`.stream()`,
  `LLMAllModelsFailedError`
- dev-board/code-review/P1-03-tools/engineer.md — `build_default_registry()`, `ToolRegistry.execute()`,
  the documented round-trip example

## Constraints / non-goals
- No LangGraph / multi-agent graph (P4).
- No Redis-backed persistent session memory (P1-05, next task) — keep the interim history seam narrow and
  documented so it's a clean swap.
- No Redis-backed cancel/stop endpoint (P1-06, next task) — don't build `/api/chat/{session}/cancel` here.
- No formal `message_id`/feedback wiring (P1-07) beyond assigning a UUID per assistant message.
- No frontend work (P1-08) — but document the SSE event vocabulary clearly since the frontend task depends
  on it verbatim.
