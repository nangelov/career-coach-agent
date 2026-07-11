# Code review — P4-02-agent-graph · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | backend/app/agents/graph.py:54 | `from langgraph.graph._node import StateNode` imports a **private** module (leading `_`). Combined with the loose `langgraph>=0.1.0` pin in pyproject.toml, a resolved pre-1.x or renamed-internals version would break the *entire* `app.agents` import at load. `StateNode` is not publicly re-exported (verified: only `langgraph.graph._node` has it). | The `PlannerNode` alias is only a test-seam type. Prefer a public-API type, e.g. `PlannerNode = Callable[[AgentState], NodeUpdate]` (mypy still accepts it into `add_node`), avoiding the private dependency. If keeping `StateNode`, tighten the pin to a `>=1.x` floor. Non-gating. |
| C2 | nit | backend/app/agents/__init__.py:2,26-27 | `__init__.py` was extended to export `build_graph`/`graph`/`run_graph`, but engineer.md "Files changed" only lists `graph.py` and `test_agent_graph.py`. The change itself is correct and sensible. | Reporting gap only — list `__init__.py` in the engineer report. No code change required. |

## Notes
- **Correctness / fan-in — the load-bearing risk — is genuinely proven.** `test_parallel_workers_fan_in_without_clobbering` dispatches all four workers concurrently via `Send` and asserts all four `worker_results` keys and four `citations` survive. Because concurrent same-superstep writes to `citations` (`operator.add`) and `worker_results` (`merge_worker_results`) would raise `InvalidUpdateError` if the P4-01 reducers weren't picked up under `from __future__ import annotations`, this passing real-graph run truly exercises the reducers (not just the reducer function). This satisfies my standing PEP-563/reducer check.
- **Conditional fan-out is correct.** `route_after_planner` returns one order-preserving, de-duplicated `Send` per selected worker; unselected workers never run (verified by test), and the no-worker case routes straight to the responder so the turn still completes. Responder runs exactly once in both paths (static worker→responder fan-in edges + the direct-Send fallback do not double-fire).
- **Guardrail/memory hooks** stamp the correct-shaped allow-all `SafetyVerdict` at input and output positions and no-op memory recall/writer with the writer terminal (pre-`END`) — stable shape for P10/P9 swap-in, matching the task's "replace body only" contract. Stubs are clearly marked (`[STUB → Pxx]`).
- **Scope respected:** `run_graph` is exposed but not wired into `/api/chat`; git diff confirms the P1 SSE endpoint and its router/service are untouched. Graph compiled once at module scope (`graph = build_graph()`), with `build_graph(planner=...)` as a narrow test seam.
- **Security:** N/A — pure graph wiring over stubs; no untrusted input reaches tools, no code execution, no secrets.
- **Verification run locally:** `ruff` clean, `mypy app/agents/graph.py tests/test_agent_graph.py` clean, `pytest tests/test_agent_graph.py` → 11 passed, full suite → 220 passed / 43 skipped. langgraph resolved to 1.2.6; the private `_node`/`CompiledStateGraph` imports resolve on that version.
