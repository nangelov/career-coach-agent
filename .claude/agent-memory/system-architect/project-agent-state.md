---
name: project-agent-state
description: Blessed P4-01 shared LangGraph state contract (AgentState) + reducer semantics that all later P4 nodes must consume
metadata:
  type: project
---

P4-01 established the typed shared state seam in `backend/app/agents/state.py`, APPROVED rev 1.

**Blessed contract (design §3):** `AgentState(BaseModel)` — Pydantic (not TypedDict; §3 says "Pydantic" literally, still LangGraph-compatible via `Annotated`). Fields: `session_id`/`user_id`(None=guest)/`role: SessionRole`, `user_message`, `message_id`, `history: list[ChatMessage]`, `memory: MemoryContext` (P9 slot), `plan: PlannerDecision`, `worker_results`, `citations`, `response`/`finish_reason`, `input_safety`/`output_safety` (P10 slots). Supporting: enums `Intent`/`WorkerName`/`GuardrailStage`, sub-models `Citation`/`WorkerResult`/`PlannerDecision`/`SafetyVerdict`/`MemoryContext`.

**Reducer rules (the load-bearing part):** parallel-writer fields carry `Annotated` reducers — `worker_results: Annotated[dict, merge_worker_results]` (key-wise, each worker owns its `WorkerName` key), `citations: Annotated[list, operator.add]`. Single-writer fields (`plan`, `response`, `finish_reason`, `input_safety`, `output_safety`) carry NO reducer (last-write-wins).

**Why:** parallel worker fan-in must not clobber; JSON round-trip needed for Redis/Celery memory-writer boundary. Reuses P1/P3 types verbatim (`SessionRole` from schemas.auth, `ChatMessage`/`message_id` from llm.types) — no parallel copies.

**How to apply (P4-02+ graph/planner/worker/responder tasks):**
- Responder is modeled as single-writer `response`/`finish_reason`, NOT a keyed worker — keep it out of `worker_results`.
- Key `worker_results` by `WorkerName`, not ad-hoc strings.
- Don't reshape this contract when P9 (memory recall) / P10 (guardrails) land — only populate the reserved `MemoryContext`/`SafetyVerdict` slots.
- Any new parallel-written field needs its own associative reducer.

Related: [[project-llm-layer-seam]] (ChatMessage source), [[project-auth-session-seam]] (SessionRole source).
