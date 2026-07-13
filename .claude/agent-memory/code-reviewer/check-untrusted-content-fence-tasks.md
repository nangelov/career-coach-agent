---
name: check-untrusted-content-fence-tasks
description: Reviewing SEC/§7.3 untrusted-content fencing + output-guardrail tasks (app/guardrails/untrusted_content.py, screen_output)
metadata:
  type: project
---

Reviewing the §7.3 "untrusted content = data, never instructions" contract (task family SEC-02, module `backend/app/guardrails/untrusted_content.py::fence_untrusted` + `heuristics.py::screen_output`).

**Why:** This is the structural half of prompt-injection defence; the real ML classifier is deferred to P10, so these minimal nets carry the guarantee in the meantime. Easy to approve blindly because it's "just fencing".

**How to apply — checks that actually catch things here:**
- **Delimiter breakout.** Fence uses fixed guessable markers (`--- BEGIN/END <LABEL> ---`) and splices untrusted blocks verbatim with no sanitisation. A block containing the literal END marker closes the fence early → breakout. Raise as minor (defence-in-depth) since it matches pre-existing responder precedent and P10 owns the classifier; required change is to neutralise the marker token inside blocks in the shared helper.
- **Per-chunk streaming scrub is strictly weaker than buffered.** `ChatService._stream_response` runs `screen_output` per `StreamChunk`; a phrase split across chunks escapes, and the persisted `parts` response stays unscrubbed. On the streaming path `graph.output_guardrail_node` never runs (GraphTurnStreamer streams the Responder directly, node is after RESPONDER in the buffered graph only), so no OUTPUT SafetyVerdict is stamped for streamed turns. Both are documented limitations → nits.
- **Verify the tool-call audit independently.** grep `tools=`/`tool_choice=` — only planner (PLANNER_TOOL_SCHEMA) and structurer (PROFILE_TOOL_SCHEMA) force a single schema; responder must have none. Confirm untrusted text (CV/crawl/posting) never shares a message with a live expandable tool schema. Audit claim "no gap" checked out.
- **DRY:** confirm one deny-list (`_DENY_PATTERNS`) backs both `screen_input` and `screen_output`, and one fence helper is used by both responder `_grounding_block` and structuring `_build_messages` — no forked copies.
- Import-cycle note is real: guardrails is a lower layer than agents; `agents.state` types must be imported lazily inside the screen functions (+ TYPE_CHECKING), else structuring/responder→guardrails closes a load cycle via agents.__init__→graph.
