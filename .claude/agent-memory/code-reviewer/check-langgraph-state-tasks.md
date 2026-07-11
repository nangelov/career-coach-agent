---
name: check-langgraph-state-tasks
description: Reviewing P4 agents/ LangGraph typed-state + reducer tasks (state.py, graph.py) — the reducer/PEP563/StrEnum-key gotchas to verify
metadata:
  type: project
---

Reviewing `backend/app/agents/` LangGraph state/graph tasks (P4). The state object is a Pydantic `BaseModel` used as `StateGraph` schema with per-field reducers via `typing.Annotated`.

**Why:** parallel worker nodes write the same channels concurrently; getting reducer semantics wrong silently clobbers data or raises `InvalidUpdateError` at graph runtime — the task's own flagged main technical risk.

**How to apply — verify these, they are the load-bearing correctness points:**
- **Reducer actually honored despite `from __future__ import annotations`.** PEP 563 stringizes annotations; the fix is that Pydantic resolves `Annotated` metadata and LangGraph reads it from `model_fields`. Don't trust the docstring — require a test that drives a **real `StateGraph` fan-out** (two nodes from START writing the same channel). If the reducer weren't picked up, LangGraph raises `InvalidUpdateError` on concurrent same-channel writes, so a passing fan-out test genuinely proves it. Bare function-call tests do NOT prove it.
- **Concurrent-accumulate fields need reducers; single-writer fields must NOT.** `worker_results` (dict, key-wise merge `{**existing, **incoming}`) and `citations` (`operator.add`) get reducers; planner decision / response / guardrail verdicts are single-writer and correctly carry none (last-write-wins).
- **StrEnum dict keys are safe to mix with plain strings.** `hash(StrEnum.MEMBER) == hash(member_value)` is True (verified P4-01), so a dict typed `dict[str, X]` written with enum keys and later JSON-round-tripped to string keys never double-stores. Not a bug — don't flag it.
- **JSON round-trip** (`model_dump_json`/`model_validate_json`) must be tested — state crosses the Redis/Celery boundary; enums must survive as typed members.
- **Type reuse** (acceptance): `SessionRole` from `app.schemas.auth`, `ChatMessage` from `app.llm.types`, `message_id` from `ChatMessage` (P1/§5.5). Reject parallel copies.

Common non-gating nit: identity invariant (`role="user"` ⟹ `user_id` present) left unenforced on the state model. Acceptable — a state object trusts its writer nodes; note it, don't gate.

**graph.py (P4-02) checks:** the load-bearing fan-in proof is a real-graph run dispatching *all* workers concurrently via `Send` and asserting every `worker_results` key + all `citations` survive (InvalidUpdateError would fire if reducers weren't honored) — that test existing+passing is the gate, not the reducer unit test. Fan-out via `route_after_planner` returning de-duped order-preserving `Send`s; no-worker case must route straight to responder so the turn completes; responder must run exactly once (static worker→responder edges + direct-Send fallback don't double-fire — check the ordering test). Guardrail/memory nodes are allow-all/no-op stubs with stable shape (P10/P9 swap body only), writer terminal pre-END. Watch for `from langgraph.graph._node import StateNode` — a **private** import (only `_node` exposes it) that with the loose `langgraph>=0.1.0` pin can break the whole `app.agents` import; flag minor, suggest `Callable[[AgentState], NodeUpdate]` for the node/test-seam type instead.
