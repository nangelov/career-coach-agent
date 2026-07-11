# Task P4-07-chat-graph-integration — Wire the multi-agent graph into `POST /api/chat`

- **Phase:** P4   **Status:** ENG   **Tags:** (B)

## Scope

Not a literal `dev-board/tasks.md` bullet by name, but required infrastructure the orchestrator is inserting
to satisfy the **P4 exit criterion**: *"a query routes planner → ≥1 worker → responder, streams, and cites
sources"* — and to unblock the remaining P4 bullets that depend on it:
> **(F)** Stream planner/worker steps to the UI.
> **(T)** A query routes through planner → ≥1 worker → responder; streams; shows citations.

`backend/app/services/chat.py`'s `ChatService` is explicitly P1's **temporary** walking skeleton — its own
module docstring says *"no LangGraph / multi-agent graph (that is P4)"*. This task makes `POST /api/chat`
actually run turns through the compiled multi-agent graph (`app/agents/graph.py`'s `stream_graph`, landed in
P4-01..P4-06) instead of the P1 single-agent LLM-router + tool-registry loop.

## What already exists — reuse, don't reinvent

- `backend/app/agents/graph.py` — `stream_graph(state: AgentState) -> AsyncIterator[StreamChunk | AgentState]`
  (P4-06): runs recall → planner → workers → responder, yielding responder token deltas then a terminal
  `AgentState` carrying `response`, `citations`, `worker_results`, `message_id`, `finish_reason`,
  `input_safety`/`output_safety` (currently pass-through stubs — P10 fills them in for real).
  `build_graph(planner=..., embedder=..., db=..., responder_router=...)` is the injection seam for the real
  collaborators (`LLMRouter`, `EmbeddingClient`, `PostgresConnectionProvider`) — wire the app's real
  singletons here (mirror how `app.bootstrap` already assembles `ChatService`'s collaborators today).
- `backend/app/agents/state.py` — `AgentState` is the graph's input/output; you'll construct one per turn from
  the same inputs `ChatService.stream_turn` currently gathers (session id, user id/role, user message, history
  slice).
- `backend/app/schemas/chat.py` — the existing SSE `ChatEvent` vocabulary (`start`/`token`/`tool_call`/
  `tool_result`/`done`/`cancelled`/`error`). Extend it **additively** — add whatever new event(s) are needed
  to surface planner/worker step visibility and citations (e.g. a `plan` event carrying intent/steps/workers,
  a `citation`/`citations` event, or fold citations into `done` — your call, document it clearly since P4's
  frontend task consumes exactly this contract) rather than replacing existing event types wholesale, so the
  wire format stays a superset of what P1-08's frontend already renders.
- `backend/app/services/cancellation.py` (`CancelRegistry`), `backend/app/services/session_memory.py`
  (`SessionMemory`), `backend/app/services/conversation_store.py` (`ConversationStore`) — the existing
  Redis-backed cancel/memory/persistence seams `ChatService` already depends on. **Preserve this behavior**:
  the graph-driven turn must still support stop/cancel (P1-06), still load/save session history (P1-05/P2-07),
  and still persist durable history for logged-in users (P2-07) — these are working, tested, cross-cutting
  concerns that must not regress. The graph itself does not own any of these; the service layer still does.
- `backend/app/api/chat.py` — the thin router; its SSE framing (`_format_sse`) and dependency wiring
  (auth/authz/rate-limit) are unaffected by this task and should not need to change (unless a new event type
  requires a schema-level change already covered by `ChatEvent` being a discriminated union).

## Implementation approach (engineer's call on exact shape, but consider)

- Swap `ChatService`'s internals to build an `AgentState` per turn (from session history + the new user
  message + `user_id`/role) and drive it through `stream_graph`, translating the yielded `StreamChunk`s into
  `TokenEvent`s and the terminal `AgentState` into `DoneEvent` (+ new citation/plan event(s)), instead of the
  current `LLMRouter`/`ToolRegistry` loop. The **cancel** check should still be observed at sensible
  checkpoints (e.g. before starting the graph run, and periodically during the responder's token stream —
  mirror the existing `cancel_check_interval` polling pattern) since a multi-agent turn is more latent than a
  single completion and users need to be able to stop it.
- Session memory / persistence: keep loading prior turns the same way, and keep persisting the produced
  user + assistant messages the same way (`SessionMemory.append`, `ConversationStore` for logged-in users) —
  this is orthogonal to *how* the assistant answer was produced.
- Tool-call visibility: the graph's workers (RAG/web-search/job-search/PDP) are **not** native LLM tool calls
  in the P1 sense — they're graph nodes the planner routes to. Decide how (or whether) to keep emitting
  `tool_call`/`tool_result`-shaped events for worker execution (repurposed to represent "a worker ran"), or
  introduce a distinct event type — whatever you choose, it must give the frontend enough to show workers
  running (this is what the paired (F) task needs to render "planner/worker steps").
  the workers running (this is what unblocks the paired (F) task, "stream planner/worker steps to the UI").
- If the existing `ChatService` test suite is large and tightly coupled to the old loop's internals (it likely
  is — check `backend/tests/` for `test_chat_service*`/similar), expect to **adapt** those tests to the new
  graph-driven mechanism rather than deleting coverage — same posture P4-05 already took adapting
  `test_agent_graph.py`'s stub-based assertions. Preserve the *contracts* under test (SSE event ordering,
  cancel behavior, persistence behavior, error handling) even where the internal implementation changed.
- Guardrail/memory-writer stub outputs (`input_safety`/`output_safety`, the no-op memory writer) just flow
  through for now — nothing to build here, P9/P10 replace those node bodies later without changing this
  integration.
- If, having read all of the above, the scope genuinely doesn't fit in one reviewable change (e.g. the
  existing `ChatService` test suite is too large to adapt safely in one pass), **stop and flag it** in your
  engineer report instead of a rushed partial change — the orchestrator will split this into a smaller
  follow-up rather than accept a task that silently drops test coverage or destabilizes P1/P3's
  auth/rate-limit/cancel guarantees.

## Acceptance criteria

- [ ] `POST /api/chat` turns are driven by `app.agents.graph.stream_graph` (planner → ≥1 worker when routed →
      responder), not the P1 raw LLM-router/tool loop.
- [ ] SSE stream still starts with `start` and ends with exactly one terminal event (`done`/`cancelled`/
      `error`), and now surfaces enough information for a client to know **which workers ran** and **what
      citations** back the answer (new event(s), additive to the existing `ChatEvent` union).
- [ ] Token-by-token streaming of the final answer is preserved (design's core "streams" requirement).
- [ ] Cancel (`POST /api/chat/{session}/cancel`) still works against a graph-driven turn.
- [ ] Session memory (Redis) and durable persistence (Postgres, logged-in users) still work exactly as before
      — same behavior, different internal mechanism producing the answer.
- [ ] AuthZ/rate-limiting at the router level (P3-04) is untouched and still enforced.
- [ ] A query that routes to ≥1 worker demonstrably produces both streamed tokens and non-empty citations
      end-to-end through the real `POST /api/chat` flow in tests (with a fake/injected router+embedder+DB, no
      live HF/Postgres).
- [ ] `ruff` + `mypy` clean; backend test suite green (adapted where the old loop's tests assumed P1-only
      internals; no unexplained coverage loss).

## Design references

- `dev-board/app-design-and-features.md` §3 — the full graph diagram this endpoint must now actually run.
- `dev-board/app-design-and-features.md` §9 — API surface (`POST /api/chat` contract).
- `dev-board/code-review/P4-01-agent-state/` .. `P4-06-responder/` — everything this task wires together.
- `dev-board/code-review/P1-04-chat-endpoint/`, `P1-05-session-memory/`, `P1-06-cancel-stream/`,
  `P1-07-message-id/`, `P2-07-persist-conversations/`, `P3-04-authz-ratelimits/` — the existing, working
  cross-cutting behavior this task must preserve.

## Constraints / non-goals

- Do NOT implement real guardrails (P10) or real memory recall/learn (P9) — the stub node bodies keep flowing
  through unchanged.
- Do NOT change `AgentState`, the graph topology, or the P4-01 reducers.
- Do NOT change router-level AuthZ/rate-limiting logic (P3-04) beyond what's incidentally needed to keep it
  working against the new internals.
- Do NOT silently drop existing test coverage for cancel/persistence/error-handling — adapt it.
- If scope is too large for one safe change, stop and report back rather than force it through.
