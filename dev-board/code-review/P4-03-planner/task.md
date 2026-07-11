# Task P4-03-planner — Planner node (intent classify, decompose, route, budget)

- **Phase:** P4   **Status:** ENG   **Tags:** (B)

## Scope

From `dev-board/tasks.md` P4:
> **(B)** `agents/planner.py` — intent classify, decompose, route to workers, set iteration/token budget.

Replace the **stub** `planner_node` body in `backend/app/agents/graph.py` (see its `[STUB → P4-03]` docstring)
with a real implementation in a new `backend/app/agents/planner.py`, and wire `graph.py` to call it. Do not
change the graph's topology/edges/conditional-routing contract (`route_after_planner`, the `PLANNER` node
name, or the `add_conditional_edges` wiring) — only swap what produces the `PlannerDecision`.

The planner (design §3):
- **Classifies intent**: `chat / job_search / pdp / cv_question / smalltalk` (`Intent` enum, already defined
  in `agents/state.py`).
- **Decomposes** the turn into a short ordered list of human-readable steps (`PlannerDecision.steps`).
- **Routes to workers**: decides which of `RAG / WEB_SEARCH / JOB_SEARCH / PDP_RESUME` (`WorkerName` enum) to
  dispatch, and in what order. Keep this conservative for now — the real RAG/web/job/PDP workers land in
  P4-04..P4-06 as stubs' replacements; the planner's routing decision is what the graph already fans out on
  (`route_after_planner`), so get the mapping intent → workers right even though most workers still return
  canned stub content until later tasks land.
- **Sets a budget**: `max_iterations` and optionally `token_budget` on `PlannerDecision`.

## Implementation approach

- Use **native tool-calling** to get a structured decision — this codebase's locked decision is no ReAct
  free-text parsing (CLAUDE.md, §6 item 2). The cleanest approach: define a tool/function JSON schema shaped
  like `PlannerDecision` (or a narrower `intent`/`workers`/`steps` selection schema), call the `LLMRouter`
  (`backend/app/llm/router.py`, already built in P1-02) with `tool_choice` forcing that tool, and parse the
  returned `ToolCall.function.arguments` into a `PlannerDecision`. Follow the pattern established by
  `backend/app/tools/` (P1-03) for how tool JSON schemas are defined/rendered in this codebase — reuse that
  convention rather than inventing a parallel one.
- The planner is a **fast/cheap classification step** (design §6.6 explicitly floats "optionally a
  cheaper/faster model for the planner vs a stronger model for the responder") — you don't have to add a
  second model tier in this task, but don't hardcode assumptions that block it later (e.g. take the
  `LLMRouter` as a constructor/module dependency rather than hand-rolling a new client).
- Handle the LLM/tool-call failure path gracefully: if the router raises or returns an unparsable/missing tool
  call, fail soft to a safe default `PlannerDecision` (e.g. `Intent.CHAT`, no workers, so the turn still
  reaches the responder) rather than raising out of the graph — a bad planner call must not 500 the whole
  turn.
- Keep the system/instruction prompt for classification in-module (or in `app/agents/` alongside), short and
  focused — this is not the full conversational system prompt, just the planning instruction.

## Acceptance criteria

- [ ] `backend/app/agents/planner.py` implements the real planning logic and produces a `PlannerDecision`
      (intent, steps, workers, max_iterations, token_budget) from the current `AgentState` (user message +
      history slice + recalled memory context already on the state).
- [ ] `graph.py`'s `planner_node` (or its default `planner=` argument in `build_graph`) is wired to this real
      implementation; the `[STUB → P4-03]` docstring marker is removed/updated. Graph topology unchanged.
- [ ] Intent → worker routing is sensible and testable: e.g. `job_search` → `[JOB_SEARCH]`, `pdp` →
      `[PDP_RESUME]`, `cv_question` → `[RAG]` (or `[RAG, PDP_RESUME]` if the CV profile is separately
      indexed — engineer's call, document it), `chat` → `[RAG]` or `[]` depending on whether the message needs
      grounding, `smalltalk` → `[]`.
- [ ] Budget fields are populated with sane defaults (`max_iterations` per design default already on
      `PlannerDecision`, `token_budget` optional).
- [ ] Failure path: router error / malformed tool call → safe default decision, does not raise out of the
      node.
- [ ] Unit tests: intent classification routes to expected workers for representative inputs (mock the
      `LLMRouter`/`LLMClient` — do not hit a real HF endpoint in tests), budget fields populated, failure path
      falls back safely, and an integration-style test running the **real compiled graph** (`build_graph`)
      with a fake/mock LLM router proves the planner's decision actually drives `route_after_planner`'s
      fan-out (only the routed workers execute).
- [ ] `ruff` + `mypy` clean; existing backend test suite (including `test_agent_graph.py` from P4-02) still
      green.

## Design references

- `dev-board/app-design-and-features.md` §3 "Multi-agent orchestration" — Planner bullet (line ~127).
- `dev-board/app-design-and-features.md` §6.6 — planner may use a cheaper/faster model tier (optional here).
- `dev-board/code-review/P4-01-agent-state/` — `Intent`, `WorkerName`, `PlannerDecision` shapes.
- `dev-board/code-review/P4-02-agent-graph/` — the graph this planner plugs into; `planner_node` stub +
  `route_after_planner` conditional fan-out + the `build_graph(planner=...)` test seam.
- `backend/app/llm/router.py` (P1-02), `backend/app/llm/client.py` (P1-01), `backend/app/tools/` (P1-03) — the
  LLM/tool-calling primitives to reuse.
- CLAUDE.md locked decisions — native tool-calling only, no ReAct text parsing.

## Constraints / non-goals

- Do NOT implement the real RAG/web-search/job-search/PDP workers (P4-04..P4-06) — they keep returning stub
  content for now; the planner just decides whether to route to them.
- Do NOT change `AgentState`, the graph's node/edge topology, or the reducers from P4-01/P4-02.
- Do NOT wire this into the P1 `POST /api/chat` endpoint yet.
- Do NOT call a live HF endpoint from unit tests — mock the router/client boundary.
