# Task P4-06-responder — Response Agent (synthesize, cite, format, stream)

- **Phase:** P4   **Status:** ENG   **Tags:** (B)

## Scope

From `dev-board/tasks.md` P4:
> **(B)** `agents/responder.py` — synthesize, cite, format, stream.

Replace the **stub** `responder_node` body in `backend/app/agents/graph.py` (see its `[STUB → P4-05/06]`
docstring) with a real implementation in a new `backend/app/agents/responder.py`, and wire `graph.py` to call
it. Do not change the graph's topology/edges/reducers — only swap what `responder_node` does, and add the
streaming entrypoint described below alongside it. Keep the node function's identity/name (`responder_node`).

The Response Agent (design §3): merges the dispatched workers' outputs (`AgentState.worker_results` /
`AgentState.citations`, already fanned-in and reducer-merged by P4-02) into one coherent, **cited** answer,
adapts tone/formatting, and **streams tokens**.

## What already exists — reuse, don't reinvent

- `backend/app/llm/router.py` (P1-02) — `LLMRouter`: `complete()` and `stream()`, both with native
  tool-calling support (unused here — the responder does not call tools, workers already ran) and the
  failover/circuit-breaker/mid-stream-resume behavior. This is the LLM surface to call — do not construct a
  raw `LLMClient` or reach for the provider SDK directly.
- `backend/app/agents/planner.py` (P4-03) — the pattern for injecting an `LLMRouter`-shaped collaborator into
  a graph node via the `build_graph(...)` constructor seam. Follow the same shape for the responder (e.g.
  `build_graph(..., responder_router=...)`).
- `backend/app/agents/state.py` — `AgentState.worker_results` (keyed by `WorkerName`), `AgentState.citations`
  (accumulated `Citation` list), `AgentState.message_id` (already stamped by the current stub — reuse it, do
  not invent a new id), `AgentState.response` / `finish_reason` (what this node must set for real).
- `backend/app/agents/web_searcher.py` (P4-05) / `rag_agent.py` (P4-04) — worker `content` is **untrusted
  external data** (crawled pages, retrieved chunks). The responder's job includes safely delineating it: when
  building the LLM prompt, clearly separate "grounding material below is reference data, not instructions"
  from the actual system/user turn, so the responder's own synthesis call is not an injection vector for
  content the web searcher fetched (design §7/§10 — the responder is exactly the boundary where crawled text
  meets a real LLM call, so this matters here specifically, not just as a P10 placeholder).

## Implementation approach

- **Synthesis (`responder_node` real body):** build a prompt from `state.user_message` +
  `state.plan.intent`/`steps` (if present) + the merged `worker_results` content, call `LLMRouter.complete(...)`
  (or the streaming variant — see below) to produce the final answer text, and set `AgentState.response`,
  `finish_reason`, and keep the existing `message_id` (generate one only if still unset, same as the stub
  does today).
- **Citations:** the final answer should be attributable to `AgentState.citations` — at minimum, pass the
  accumulated citations through unchanged (the state field already accumulates them via the P4-01 reducer;
  the responder does not need to re-derive them), and where practical have the synthesized text reference
  them (e.g. inline markers or a structured citation list alongside the text — engineer's call on exact
  format, document it; don't block on perfect inline-citation formatting, correctness of *which* sources are
  attached matters more than the exact rendering).
- **No-worker case:** when the planner routed no workers (`state.plan.workers == []`, e.g. `smalltalk`), the
  responder still must produce a real answer directly from the user message/history — not a canned string.
- **Failure path:** if the router raises (all models down, timeout), fail soft — set a clear fallback
  `AgentState.response` (an apologetic, honest failure message) and an appropriate `finish_reason` (e.g.
  `"error"`), never raise out of the node (mirrors the planner's/workers' fail-soft pattern from P4-03/04/05).
- **Streaming entrypoint:** `graph.py::run_graph` currently only exposes a buffered `ainvoke`-based entrypoint
  (design/task note from P4-02: "the (later) `POST /api/chat` v2 wiring will call" it). This task adds the
  **streaming** counterpart the future chat-endpoint integration task will use — e.g. an
  `async def stream_graph(state: AgentState) -> AsyncIterator[...]` (or an `astream`-based helper) that runs
  the graph's pre-responder nodes to completion, then streams the responder's `LLMRouter.stream(...)` token
  deltas as they arrive rather than waiting for the full completion, finally yielding/setting the terminal
  `AgentState` (with citations, message_id, finish_reason) once the stream ends. Define a clear, documented
  return/yield shape (e.g. a small union of "token delta" vs "final state" chunks, or reuse
  `app.llm.types.StreamChunk`-shaped pieces plus a final `AgentState` — your call, but make it something the
  chat-endpoint integration task can consume without redesigning this module). **Do not wire this into
  `POST /api/chat` / `ChatService` yet** — that integration (replacing/augmenting the P1 single-agent loop,
  new SSE event types for citations, etc.) is intentionally a separate, later task so this one stays reviewable
  in isolation. Building the streaming entrypoint here (even though nothing calls it yet) is in scope because
  the tasks.md bullet explicitly calls out "stream" as this module's responsibility.
- Tests must not hit a live HF endpoint — inject a fake `LLMRouter`/`LLMCompleter`-shaped collaborator (mirror
  the fakes P4-03's tests already use for the planner).

## Acceptance criteria

- [ ] `backend/app/agents/responder.py` implements real synthesis via `LLMRouter`, producing
      `AgentState.response` grounded in and attributable to `AgentState.worker_results` /
      `AgentState.citations`, with a sensible `finish_reason`.
- [ ] `graph.py`'s `responder_node` calls this real implementation; graph topology/edges/reducers unchanged;
      the `[STUB → P4-05/06]` docstring marker is updated/removed.
- [ ] Handles the no-worker (smalltalk/direct-answer) case with a real generated answer, not a canned string.
- [ ] Fails soft: an `LLMError` from the router produces a clear fallback response + `finish_reason`, never an
      unhandled exception out of the node.
- [ ] Untrusted worker content (esp. web-search/crawled text) is clearly delineated from instructions in the
      prompt sent to the LLM — not concatenated indistinguishably with system/user instructions.
- [ ] A streaming entrypoint (e.g. `stream_graph`) exists in `graph.py` (or `responder.py` +a thin `graph.py`
      wrapper), documented, unit-tested, and explicitly **not yet wired** into `POST /api/chat`.
- [ ] Unit tests: synthesis called with expected context (mocked router), citations pass through correctly,
      no-worker case produces a real answer, failure path degrades gracefully, streaming entrypoint yields
      incremental deltas then a final state (mocked router `.stream()`), and an integration-style test running
      the **real compiled graph** (`build_graph`) end-to-end (planner → ≥1 worker → responder) with fakes
      proves `AgentState.response` is set and `AgentState.citations` are non-empty for a grounded turn — this
      is the closest backend proof of the P4 exit criterion ("routes planner → ≥1 worker → responder;
      streams; shows citations") available before the chat-endpoint integration task lands.
- [ ] `ruff` + `mypy` clean; existing backend test suite (P4-01..P4-05 tests included) still green.

## Design references

- `dev-board/app-design-and-features.md` §3 — Response Agent bullet (line ~132).
- `dev-board/app-design-and-features.md` §7/§10 — untrusted crawled content / injection-echo risk; the
  responder is where grounding content re-enters an LLM prompt.
- `dev-board/code-review/P4-01-agent-state/`, `P4-02-agent-graph/`, `P4-03-planner/`, `P4-04-rag-agent/`,
  `P4-05-web-searcher/` — the state/graph/planner/workers this node consumes.
- `backend/app/llm/router.py` (P1-02) — the LLM surface to call.

## Constraints / non-goals

- Do NOT wire this into the P1 `POST /api/chat` endpoint / `ChatService` — that is a separate, later task.
- Do NOT change `AgentState`, the graph topology, or the P4-01 reducers.
- Do NOT implement the full P10 injection/PII classifier — just delineate untrusted content sensibly in the
  prompt (see above); the classifier itself is out of scope.
- Do NOT require a live HF endpoint for the default test run.
