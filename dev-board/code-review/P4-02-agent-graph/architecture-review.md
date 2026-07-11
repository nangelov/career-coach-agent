# Architecture review — P4-02-agent-graph · engineer revision 1

## Verdict: APPROVED

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | `agents/graph.py` = "LangGraph wiring" | `backend/app/agents/graph.py` is the wiring-only module; `state.py` consumed unchanged | none |
| A2 | §3 node sequence | Guardrails(in) → Memory recall → Planner → {RAG, Web, Job, PDP} → Response → Guardrails(out) → Memory writer | `START → input_guardrail → memory_recall → planner → {4 workers} → responder → output_guardrail → memory_writer → END` — exact 1:1 match | none |
| A3 | §3 planner routing | Planner "decides which workers run" (not always all) | Conditional fan-out via `Send` (`route_after_planner`); only `PlannerDecision.workers` dispatched, unselected never run; no-worker → responder fallback | none |
| A4 | §3 parallel workers + P4-01 reducers | Concurrent worker fan-in must not clobber `worker_results`/`citations` | Static `worker → responder` edges converge; merge delegated to P4-01 reducers (`merge_worker_results`/`operator.add`), not re-derived; exercised through a real 4-worker graph run | none |
| A5 | §3 typed shared state | "typed object (Pydantic)" threaded through nodes | `StateGraph(AgentState)`; nodes return partial `NodeUpdate` dicts folded per-field; responder kept single-writer (`response`/`finish_reason`), not a keyed worker — matches blessed [[project-agent-state]] ruling | none |
| A6 | §3 guardrails (P10 slot) | Minimal input/output guardrail hooks now, real logic P10 | Bracketing stubs stamp allow-all `SafetyVerdict` of correct shape into `input_safety`/`output_safety`; body-only swap for P10, stable hook | none |
| A7 | §3/§5.4 memory (P9 slot) | Recall before planning; writer post-turn async/Celery | `memory_recall_node` pre-planner no-op; `memory_writer_node` terminal no-op positioned post-response; `MemoryContext` slot reserved, untouched | none — see Note N1 |
| A8 | Locked decision | LangGraph orchestration, hand-rolled orchestrator rejected; no ReAct parser | Pure LangGraph `StateGraph`/`Send`/conditional edges; no text-parser reintroduced | none |
| A9 | Phase fit / non-goals | Wire shape only; no real planner/worker/responder/guardrail/memory logic; don't touch P1 `/api/chat` | All node bodies are marked `[STUB → Pxx]`; `run_graph` entrypoint exposed but not wired into `api/chat.py`; P1 SSE endpoint untouched | none |
| A10 | Compile-once | Graph built once, not per request | Module-level `graph = build_graph()`; `build_graph(planner=...)` factory is a narrow test seam only | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — Agent layer only; no Router/Service/DB-driver coupling; not wired into any router yet.
- [x] Honors locked decisions — LangGraph orchestration, typed shared state, no ReAct parser; no datastore/auth surface touched.
- [x] Interfaces-before-implementations — worker/planner/responder are named `def` node seams swappable in place; `PlannerNode` typed test seam; graph topology is the stable contract.
- [x] Budget posture respected — no new paid dependency; stubs only.

## Notes
- **N1 (P9 follow-up, not a blocker):** the memory-writer is wired as a **synchronous terminal in-graph node**. Design §3 labels it "async, Celery." The engineer positioned it correctly (post-response, terminal) so the *topology* is right, but when P9 makes it real it will likely be dispatched fire-and-forget (Celery) rather than blocking the graph before `END`. The current shape keeps the turn blocking on a no-op, which is harmless now; P9 should decide whether the writer stays an in-graph node or becomes an out-of-band task kicked from this position. No shape change is forced by this task — logged so P9 doesn't treat the sync node as settled.
- **N2 (naming, informational):** worker **node** names come from `WorkerName` enum values (`web_search`, `job_search`, `pdp_resume`); §8 **file** names for the future real workers are `web_searcher.py`/`job_agent.py`/`pdp_agent.py`. No conflict — node identity vs. module filename are different axes; the 1:1 mapping of node name ↔ `WorkerName` is the right choice and keeps the planner's routing vocabulary aligned to the graph.
- **N3:** SSE streaming to the client (design §3: stream happens at the output-guardrail boundary, before memory writer) is intentionally out of scope here; `run_graph` returns final state and the streaming integration is a later `/api/chat` task. Correct deferral.
- Consistent with prior rulings [[project-agent-state]] (responder single-writer, `worker_results` keyed by `WorkerName`, reducers not reshaped) and [[project-llm-layer-seam]] (no parallel type copies).

## Verdict: APPROVED
