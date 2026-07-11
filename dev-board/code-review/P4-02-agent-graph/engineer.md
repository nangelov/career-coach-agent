# Engineer report — P4-02-agent-graph · Revision 1

## Summary
Wired the multi-agent LangGraph turn graph (design §3) in `backend/app/agents/graph.py`, threading the
`AgentState` (P4-01) through the full node sequence:

```
START → input_guardrail → memory_recall → planner
      → {rag, web_search, job_search, pdp_resume}  (conditional fan-out, parallel)
      → responder (fan-in) → output_guardrail → memory_writer → END
```

Every node body is a deliberately-temporary stub (guardrails → P10, memory recall/writer → P9,
planner → P4-03, workers → P4-04..P4-06, responder → P4-05/06), each annotated with the task that
replaces it. The graph *shape* (nodes, edges, conditional routing, fan-in) is the real deliverable and is
contracted to stay stable when the stub bodies are swapped in place. Conditional fan-out uses LangGraph's
`Send` API so only planner-selected workers run; fan-in relies on the P4-01 reducers
(`merge_worker_results` / `operator.add`) to merge concurrent worker writes. The graph is compiled once at
import (`graph`), with a `build_graph(planner=...)` factory exposing a test seam, and a stable
`async def run_graph(state) -> AgentState` entrypoint (not yet wired into `/api/chat`, per task).

**Context:** a prior run left `graph.py` and `test_agent_graph.py` on disk but never finished or reported.
I reviewed both critically against the acceptance criteria. `graph.py` was already lint/type-clean and
functionally correct (named-`def` worker nodes + shared `_worker_update` helper + `PlannerNode =
StateNode[AgentState, Any]` seam — the typing refactor the prior run was mid-way through was in fact
complete in the module). The only broken part was **2 mypy annotation errors in the test file** (missing
return/param annotations); I fixed those. No production-code changes were required beyond verification.

## Files changed
- `backend/app/agents/graph.py` — reviewed; already complete and clean (no changes needed this pass).
- `backend/tests/test_agent_graph.py` — added missing type annotations: `_planner_selecting -> PlannerNode`
  and `_node_order(compiled: CompiledStateGraph[AgentState], ...)`; imported `PlannerNode` from the graph
  module and `CompiledStateGraph` from `langgraph.graph.state` to make the suite mypy-clean.

## Key decisions
- **Conditional fan-out via `Send`** (design §3 "planner routes to workers"): `route_after_planner` returns
  one `Send(worker, state)` per selected worker (de-duped, order-preserving); with no workers it routes
  straight to the responder so the turn still completes. Unselected workers never execute.
- **Fan-in through the P4-01 reducers, not re-derived here** (acceptance criteria): static `worker → responder`
  edges converge; concurrent writes merge via `AgentState`'s declared reducers. Tests exercise this through a
  real graph run (all four workers), not by unit-testing the reducer again.
- **Stubs with a stable hook shape**: guardrail nodes stamp an allow-all `SafetyVerdict` of the correct shape
  (P10 swaps the body only); memory recall/writer are no-ops positioned correctly (writer terminal, post-
  response, to become async/Celery in P9) so the topology never has to change.
- **Compile once** (`graph = build_graph()` at module scope); `run_graph` re-validates the LangGraph result
  into a first-party `AgentState`.
- **Left 2 pre-existing, out-of-scope mypy errors untouched** — see Tests section.

## How to verify
```bash
cd backend
.venv/bin/ruff check app/agents/graph.py tests/test_agent_graph.py
.venv/bin/mypy app/agents/graph.py tests/test_agent_graph.py
.venv/bin/python -m pytest tests/test_agent_graph.py -q
```

## Tests (final step — mandatory)
- `ruff check app/ tests/` → **All checks passed!**
- `mypy app/` → **Success: no issues found in 64 source files**
- `mypy app/agents/graph.py tests/test_agent_graph.py` → **Success: no issues found in 2 source files**
- `pytest` (full suite) → **220 passed, 43 skipped in 3.17s**
- `pytest tests/test_agent_graph.py` → **11 passed** (node ordering, guardrail bracketing, conditional
  fan-out to only selected workers, no-worker→responder fallback, dedupe, parallel fan-in without clobbering,
  responder merge, allow-all guardrail verdicts, compiled-once singleton, `run_graph` validated state).

**Root-cause fix this pass:** the only failing check was mypy on `tests/test_agent_graph.py` (2
`no-untyped-def` errors on the two test helpers). Root cause was missing annotations in the prior draft, not
a code defect — fixed by annotating both helpers with the real types (`PlannerNode`,
`CompiledStateGraph[AgentState]`). Re-ran until green.

**Known pre-existing mypy errors — NOT regressions, NOT in scope for P4-02:** `mypy tests/` also reports
`tests/test_message_id.py:71` (`FakeRegistry` vs `ToolRegistry`) and `tests/test_llm_router.py:309`
(unused `type: ignore`). Both files are from P1/P2, are unmodified by this task (`git status` shows no
changes), and CI type-checks only `app/`+`migrations/` (not `tests/`), so they don't gate CI. I did not
touch them to avoid scope creep into other tasks' test files; flagging so the reviewer knows they predate
this change. Happy to fix in a follow-up if desired.

## Self-check
- [x] Meets acceptance criteria — compiled `StateGraph[AgentState]`, conditional fan-out via `Send`, fan-in
  through P4-01 reducers, bracketing guardrail stubs (allowed verdict, stable shape), terminal memory-writer
  stub, `run_graph` entrypoint, compiled-once singleton, integration tests through the real graph.
- [x] No secrets committed; layering respected (this is the Agent layer; not wired into any Router/Service,
  and the existing P1 `/api/chat` endpoint is untouched).
- [x] Tests/lints pass (pasted above); task files are ruff + mypy clean and the full suite is green.
- [x] Stubs clearly marked (`[STUB → Pxx]` docstrings + module docstring map) so later tasks know exactly
  what to replace without changing the wiring contract.
