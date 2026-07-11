---
name: pattern-planner-classify-route-split
description: Blessed P4 planner pattern — LLM classifies intent, code derives worker routing deterministically
metadata:
  type: project
---

The P4-03 planner (`app/agents/planner.py`) splits **classification** (the LLM assigns one
`Intent` + writes steps, via a single forced native tool-call `record_plan`) from **routing**
(worker fan-out derived deterministically from the intent via `_INTENT_WORKERS` / `_workers_for`).
The model never emits node/worker names.

**Why:** Conservative and unit-testable while the RAG/web/job/PDP workers are still stubs
(P4-04..P4-06). Honors the locked native-tool-calling / no-ReAct decision. Keeps the graph's
`route_after_planner` fan-out contract stable.

**How to apply:** When reviewing P4-04..P4-06 (and later routing changes), require worker routing
to extend the deterministic `_INTENT_WORKERS` / `_workers_for` mapping — do not accept the model
emitting worker/node names directly. The LLM surface must stay injected via the `LLMCompleter`
Protocol (structural match to `LLMRouter.complete`), never a hand-rolled client or DB coupling, so
the §6.6 cheaper-planner-model-tier option stays a wiring change. Fail-soft catches the router's
`LLMError` contract (not bare `Exception`) → safe default `PlannerDecision`. See
[[pattern-p1-walking-skeleton]].
