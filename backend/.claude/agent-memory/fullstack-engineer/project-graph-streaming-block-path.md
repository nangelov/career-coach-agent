---
name: project-graph-streaming-block-path
description: The chat streaming path streams the responder SEPARATELY from the pre-responder graph — a graph node setting AgentState.response is not enough to change the streamed answer
metadata:
  type: project
---

The P4 chat turn runs in **two phases** that are decoupled: `GraphTurnStreamer.plan()`
runs the *pre-responder* compiled graph (guardrails → recall → planner → workers → a
deterministic responder tail whose placeholder answer is **discarded**), then
`stream_response()` streams the **real** `Responder` LLM over the merged state.

**Why it matters:** setting `AgentState.response` inside a graph node (e.g. a guardrail
short-circuit refusal) is enough for the buffered `run_graph`/`ainvoke` path, but the
streaming path (`ChatService` → `GraphTurnStreamer`) will still call the real responder
and stream *its* tokens — the node-set `response` is ignored unless `stream_response`
explicitly reads it.

**How to apply:** any feature that must alter/short-circuit the streamed answer without an
LLM call has to change BOTH: (1) the graph node/routing (so `plan()`'s pre-graph skips the
planner/workers — a conditional edge after the relevant node) AND (2) `stream_response`
(so it yields the canned/alternate chunk instead of calling `self._responder.stream`).
`ChatService.stream_turn` needs no change — a blocked turn with `plan is None` already
skips the `PlanEvent` and its normal token→done loop turns the refusal chunk into a
clean `done` (not `error`). Verify "LLM never called" by spying on the injected router's
`complete`/`stream` (both empty). See `route_after_input_guardrail` (P4-08).
