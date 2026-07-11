---
name: ruling-responder-p4-06-scope
description: Blessed P4-06 Response Agent scope — DI seam, untrusted-content fencing, citations pass-through, and two P9 follow-ups
metadata:
  type: project
---

The P4-06 Response Agent (`app/agents/responder.py`) was approved. Patterns blessed here that P9 (and the
later chat-endpoint SSE integration) must honor:

**Blessed.**
- Responder synthesizes via an injected `LLMResponder` Protocol (structural match to `LLMRouter.complete`/
  `.stream`), wired by `build_graph(responder_router=...)` — same DI shape as the planner
  ([[pattern-planner-classify-route-split]]). Model-tier swap (§6.6 stronger responder) stays a wiring change.
- Untrusted worker/crawled content (§7/§10) is fenced in a labelled `BEGIN/END REFERENCE MATERIAL` system
  message with an ignore-embedded-directives preface — the responder is exactly the boundary where crawled
  text re-enters an LLM prompt; require this fencing to survive future edits.
- Citations pass through untouched (node returns only `response`/`finish_reason`/`message_id`); re-writing
  would double them under the P4-01 list-concat reducer.
- `message_id` reuses `state.message_id`, mints only if unset — terminal-answer stamping per
  [[ruling-message-id-feedback-key]]. Fail-soft on `LLMError` → `FALLBACK_RESPONSE` + `finish_reason="error"`.

**Two follow-ups deferred to later tasks (do not re-litigate, but enforce when those tasks land):**
1. **P9 must wire `state.memory` into the responder prompt**, not just the planner. §3 says the responder owns
   tone "adapted to the user's learned communication style"; `_build_messages` does not read `state.memory`
   yet (fine now — `memory_recall_node` is a P9 no-op). Flag any P9 recall design that injects memory only into
   the planner.
2. **`stream_graph` runs the output-guardrail/memory-writer tail on the discarded placeholder answer**, not the
   streamed one (it runs the LLM-free `build_graph()` for merged worker state, then streams the real Responder).
   **UPDATE (P4-07 approved 2026-07-11):** this placeholder-answer tail is now knowingly wired into
   `POST /api/chat` — `GraphTurnStreamer._pre_graph` includes `OUTPUT_GUARDRAIL`→`MEMORY_WRITER`, run in
   `plan()` over the LLM-free placeholder; the real streamed answer (`ChatService` `result.content`) bypasses
   both. Approved anyway: nodes are inert stubs (zero impact), forcing a post-stream tail now is speculative
   scaffolding (YAGNI), and the fix is entangled with P9/P10 design (redaction vs. token-by-token SSE tension).
   Compiled-once reuse IS satisfied (streamer compiles once; bootstrap builds once/process).
   **ENFORCE at P9/P10:** the memory writer (P9) and output guardrail (P10) are NOT pure node-body swaps —
   they must restructure the post-response path to run over the *actual streamed answer*. Reject any P9/P10
   plan that assumes "just swap the node body."
