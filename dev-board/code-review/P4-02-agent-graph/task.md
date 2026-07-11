# Task P4-02-agent-graph — LangGraph wiring

- **Phase:** P4   **Status:** ENG   **Tags:** (B)

## Scope

From `dev-board/tasks.md` P4:
> **(B)** `agents/graph.py` — LangGraph wiring (recall → planner → workers → responder → guardrails → memory-writer).

Build `backend/app/agents/graph.py`: the `StateGraph` (using `AgentState` from `backend/app/agents/state.py`,
already merged in `P4-01-agent-state`) that wires the node sequence from design §3's diagram:

```
Guardrails(input) → Memory recall → Planner → {RAG, Web Searcher, Job Search, PDP/Resume} (fan-out, parallel)
  → Response Agent (fan-in) → Guardrails(output) → Memory writer (async/Celery, post-turn)
```

**Chicken-and-egg note (read this first):** `planner.py`, `rag_agent.py`, `web_searcher.py`, and `responder.py`
are **separate, later P4 tasks** (P4-03..P4-06) not yet implemented. To wire and test the graph *now*, add
**thin placeholder node callables** for planner/workers/responder/guardrails/memory-writer directly in
`graph.py` (or tiny stub functions colocated there) that satisfy the node signature LangGraph expects and
produce a plausible, minimal `AgentState` update (e.g. planner stub sets a hardcoded `PlannerDecision` routing
to no workers or one worker; a worker stub returns a canned `WorkerResult`; responder stub echoes something
into `response`). Document clearly (module docstring + inline comments) that these are placeholders to be
**replaced in place** by P4-03..P4-06 without changing the graph's wiring/edges/conditional-routing contract.
Do not build real planner intent-classification, real retrieval, real web search, or real synthesis here —
that would duplicate/conflict with the dedicated tasks that follow.

## Acceptance criteria

- [ ] `backend/app/agents/graph.py` defines a compiled LangGraph `StateGraph[AgentState]` (or equivalent
      current LangGraph API) implementing the node sequence above, including:
  - Conditional fan-out from the planner to only the workers it selected (`PlannerDecision.workers`), not
    always all four — use LangGraph's conditional-edges / `Send` API so unselected workers don't run.
  - Fan-in from parallel workers into the responder (relies on the `P4-01` reducers on `worker_results` /
    `citations` so concurrent worker writes merge safely — do not re-derive that logic here).
  - An input-guardrail node before recall/planner and an output-guardrail node after the responder, wired as
    **pass-through stubs** that populate `AgentState.input_safety` / `output_safety` with an "allowed" verdict
    (real guardrail logic is P10 — task explicitly says "Minimal input guardrails wired here (completed in
    P10)"). Keep the hook shape stable so P10 only needs to swap the stub body.
  - A memory-writer step wired as the terminal node, stubbed as a no-op (real LangMem recall/learn logic is
    P9) — but positioned correctly (post-response, would run async/Celery in P9) so the graph shape doesn't
    need to change later.
- [ ] Expose a small, stable entrypoint (e.g. `async def run_graph(state: AgentState) -> AgentState` or a
      streaming variant) that the (not-yet-built) `POST /api/chat` v2 wiring / graph invocation site can call.
      Do not wire this into `api/chat.py` yet — that integration belongs to a later task once responder/planner
      are real (avoid touching the existing, working P1 `/api/chat` SSE endpoint in this task).
- [ ] Graph is constructed once (module-level `graph = builder.compile()` or a factory) — not rebuilt per
      request.
- [ ] Unit/integration tests: build the graph, run a turn end-to-end through the stub nodes, assert the state
      flows through every node in the right order (e.g. via a trace/log or by asserting each stub's marker
      landed in the final state), assert conditional routing only invokes planner-selected workers, assert
      parallel workers don't clobber each other's `worker_results`/`citations` (exercise the P4-01 reducers
      through a real graph run, not just unit-testing the reducer function again).
- [ ] `ruff` + `mypy` clean; existing backend test suite still green.

## Design references

- `dev-board/app-design-and-features.md` §3 "Multi-agent orchestration" — the graph diagram (lines ~86-136)
  and node list this task wires.
- `dev-board/app-design-and-features.md` §8 "Target Project Structure" — `agents/graph.py` location.
- `dev-board/code-review/P4-01-agent-state/` — the `AgentState` object and its reducers this graph threads.
- CLAUDE.md locked decisions — LangGraph orchestration (confirmed, hand-rolled orchestrator rejected).

## Constraints / non-goals

- Do NOT implement real planner/RAG/web-search/job-search/PDP/responder logic — those are P4-03..P4-06 and
  will replace the stubs in place.
- Do NOT implement real guardrail logic (P10) or real memory recall/learn (P9) — stubs only, correct shape.
- Do NOT touch the existing P1 `POST /api/chat` endpoint or its router/service/agent loop — this graph is not
  wired into it yet.
- Keep the stub node bodies obviously temporary (clear naming/docstrings) so later tasks know exactly what to
  replace.
