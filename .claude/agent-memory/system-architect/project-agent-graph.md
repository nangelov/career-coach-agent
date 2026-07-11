---
name: project-agent-graph
description: Blessed P4-02 LangGraph wiring contract (graph shape, Send fan-out, stub-body-swap seam) that P4-03..P4-06/P9/P10 must preserve
metadata:
  type: project
---

P4-02 wired the multi-agent turn graph in `backend/app/agents/graph.py`, APPROVED rev 1. The **graph shape is the deliverable**; every node body is a `[STUB → Pxx]` swapped in place later.

**Blessed topology (design §3, exact match):** `START → input_guardrail → memory_recall → planner → {rag, web_search, job_search, pdp_resume} → responder → output_guardrail → memory_writer → END`.

- **Fan-out:** conditional via LangGraph `Send` (`route_after_planner`) — only `PlannerDecision.workers` dispatched (de-duped, order-preserving); no workers → straight to responder. Unselected workers never run.
- **Fan-in:** static `worker → responder` edges; merge delegated to P4-01 reducers, NOT re-derived here.
- **Worker node names = `WorkerName` enum values** (`web_search`/`job_search`/`pdp_resume`) so planner routing vocabulary maps 1:1 to graph nodes. (§8 *file* names differ: `web_searcher.py`/`job_agent.py`/`pdp_agent.py` — node-name vs filename are different axes, no conflict.)
- **Compile once:** module-level `graph = build_graph()`; `build_graph(planner=...)` factory is a narrow **test seam only** (drive routings until P4-03). `run_graph(state) -> AgentState` is the stable entrypoint, NOT yet wired into `/api/chat`.

**Why:** the wiring/edges/conditional-routing is contracted stable; P4-03..P4-06 swap node *bodies* in place (planner_node→P4-03, workers→P4-04..06, responder→P4-05/06), P10 swaps guardrail bodies, P9 swaps memory recall/writer bodies — none reshape the graph.

**How to apply (P4-03..P4-06, P9, P10):**
- Replace only the node function body; do not add/remove edges or change fan-out/fan-in unless the design diagram changes.
- Real planner (P4-03) replaces `planner_node` body (not the `build_graph(planner=)` seam).
- **P9 open item:** memory_writer is currently a **synchronous in-graph terminal node** (no-op). Design §3 says "async, Celery" — P9 must decide whether it stays an in-graph node or becomes fire-and-forth Celery dispatch from that position. Position is right; sync-vs-async is NOT settled.
- SSE streaming (stream at output-guardrail boundary) deferred to the `/api/chat` integration task, not the graph.

Related: [[project-agent-state]] (the AgentState/reducers this graph threads), [[project-llm-layer-seam]].
