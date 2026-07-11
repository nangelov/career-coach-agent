# Task P4-01-agent-state — Typed shared LangGraph state

- **Phase:** P4   **Status:** ENG   **Tags:** (B)

## Scope

From `dev-board/tasks.md` P4:
> **(B)** `agents/state.py` — typed shared Pydantic state (ids, history slice, planner decisions, worker
> results, citations, safety verdicts).

Create `backend/app/agents/state.py` defining the typed state object that will be threaded through every node
of the LangGraph multi-agent graph built across the rest of P4 (recall → planner → workers → responder →
guardrails → memory-writer). This task is state-only: no graph wiring, no planner/worker/responder nodes yet
(those are separate P4 tasks: `agents/graph.py`, `agents/planner.py`, `agents/rag_agent.py`,
`agents/web_searcher.py`, `agents/responder.py`). Keep scope to the state model (+ any small supporting
enums/typed sub-models it needs) and unit tests for it.

## Acceptance criteria

- [ ] `backend/app/agents/state.py` defines a typed Pydantic (or Pydantic-backed `TypedDict`, whichever is
      idiomatic for LangGraph state — engineer's call, document the choice) object holding at minimum, per
      design §3 ("State between nodes is a typed object (Pydantic) holding: user/session ids, message history
      slice, planner decisions, per-worker results, citations, and safety verdicts"):
  - user id (nullable — guests) and session id
  - a slice of conversation history (recent turns) usable as LLM input
  - planner decisions: classified intent, decomposed steps/plan, which workers to run, iteration/token budget
    (see design §3 "Planner" bullet — classify intent, decompose, route to workers, set budget)
  - per-worker results, keyed by worker/agent name, in a shape that can accumulate across parallel workers
  - citations (source snippets/links used for grounding, per design §3's Response Agent "synthesize, cite
    sources")
  - safety verdicts (input + output guardrail results — placeholder fields are fine since guardrails land
    fully in P10, but the shape must exist now so P4's minimal guardrail hook and P10 can both write to it)
  - recalled memory/preferences slot (design §3 "Memory recall" step feeds context before planning) — needed
    so P9's memory work has a home, even if unused until then
  - streaming/message-id bookkeeping needed by the responder (reuse the existing `message_id` convention from
    P1, don't invent a new one)
- [ ] State is designed to compose with LangGraph's `StateGraph` reducer/annotation patterns (e.g.
      `Annotated[list, operator.add]` or LangGraph's `add_messages`-style reducers) so parallel worker nodes
      can each write their own slice without clobbering others' updates. This is the main technical risk of
      this task — get the reducer semantics right, since P4's later `graph.py` task depends on it.
- [ ] Reuses existing schemas/types where they already exist in the codebase (e.g. message schemas from P1
      chat endpoint / P2 persistence, session/user id types from P3 auth) instead of redefining parallel
      copies — check `backend/app/schemas/`, `backend/app/api/chat.py`, and repositories before inventing new
      types.
- [ ] Unit tests: state construction, reducer/merge behavior for concurrent worker writes, serialization
      round-trip (state must be JSON-serializable for Redis/Celery boundary use), and any validation the model
      enforces.
- [ ] `ruff` + `mypy` clean; existing backend test suite still green.

## Design references

- `dev-board/plan.md`: P4 — Multi-agent orchestration.
- `dev-board/app-design-and-features.md` §3 "Multi-agent orchestration (the core of v2)" — graph diagram, node
  list, and the state-object description (line ~136: "State between nodes is a typed object (Pydantic)
  holding: user/session ids, message history slice, planner decisions, per-worker results, citations, and
  safety verdicts.").
- `dev-board/app-design-and-features.md` §8 "Target Project Structure" — `agents/state.py` location.
- CLAUDE.md locked decisions — LangGraph orchestration; no ReAct text parser; native tool-calling.

## Constraints / non-goals

- Do NOT implement `graph.py`, `planner.py`, `rag_agent.py`, `web_searcher.py`, `job_agent.py`, `pdp_agent.py`,
  or `responder.py` in this task — those are separate P4 tasks that will consume this state object.
- Do NOT wire guardrails logic (P10) or memory recall/learn logic (P9) — only reserve the state fields they'll
  need.
- Do NOT touch `POST /api/chat` or existing P1 chat flow; this is a new, currently-unused module until
  `graph.py` lands.
