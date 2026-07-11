---
name: ruling-input-guardrail-p4-08-seam
description: Blessed P4-08 minimal input guardrail — screen_input->SafetyVerdict seam, block routes to OUTPUT_GUARDRAIL, P10 swaps detection only
metadata:
  type: project
---

The P4-08 minimal input guardrail (`app/guardrails/heuristics.py` + `route_after_input_guardrail`
in `app/agents/graph.py`) was approved. Patterns blessed here that P10 must honor:

**Blessed.**
- **Seam:** `screen_input(message) -> SafetyVerdict(stage=INPUT)` is the stable contract; the graph
  routes on the returned verdict via `route_after_input_guardrail`. P10 replaces the deny-list
  detection **wholesale** without touching graph wiring. Heuristic lives in reserved
  `app/guardrails/` (§8). Pure `re` regex — no LLM, no ML dep, no network (budget §11 clean).
- **Topology change is a single conditional edge.** `INPUT_GUARDRAIL` now has
  `add_conditional_edges(..., [MEMORY_RECALL, OUTPUT_GUARDRAIL])`; all other P4-02 edges untouched.
  A blocked turn short-circuits `INPUT_GUARDRAIL → OUTPUT_GUARDRAIL → MEMORY_WRITER → END`, skipping
  planner/workers/responder (no wasted LLM call, no tool/API side effect — satisfies §7 "before
  content hits tools").
- **Block routes to OUTPUT_GUARDRAIL, not RESPONDER — correct for the split-phase streamer.** The
  real answer is streamed separately by `GraphTurnStreamer.stream_response`, which would discard a
  pre-graph RESPONDER placeholder. Refusal is stamped into `state.response` during `plan()`; the
  streamer emits it as one terminal chunk when `input_safety.allowed is False` (no LLM call).
- **Default-open, small documented deny-list** marked P10-replaceable. Deny-list *breadth* is a
  code-reviewer concern, not design-conformance. `ChatService` needs no change (blocked turn →
  `plan is None` → no PlanEvent → refusal chunk → normal `done`, not `error`).
- Reuses existing `SafetyVerdict`/`GuardrailStage` — no `AgentState`/reducer change. `message_id`
  reuse follows [[ruling-message-id-feedback-key]] / [[ruling-responder-p4-06-scope]].

**Relation to the P4-07 streaming-tail ruling ([[ruling-responder-p4-06-scope]]):** the blocked-path
tail runs over the *actual* refusal text (set in `plan()`), so it does NOT conflict with the standing
P9/P10 enforcement that the post-response path be restructured for the *streamed* answer — that note
targets the allowed streamed path only. Blocked turns are already correct.
