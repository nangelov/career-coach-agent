# Architecture review — P4-06-responder · engineer revision 1

## Verdict: APPROVED

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Response Agent lives at `agents/responder.py` | New `app/agents/responder.py`; graph node wired in `agents/graph.py`; exports via `agents/__init__.py` | None — correct module placement |
| A2 | §3 Response Agent | Merge worker outputs into one coherent, cited answer; own tone/formatting; stream tokens | `Responder.synthesize` (buffered) + `Responder.stream` (token deltas) synthesize from merged `worker_results` + `citations`; `stream_graph` streams | None |
| A3 | Layering (Router→Service→Agent) | Agent calls the LLM via a seam, never a raw client/SDK | Depends on `LLMResponder` structural Protocol (mirrors `LLMRouter.complete`/`.stream`); `LLMRouter` satisfies it; no provider SDK, no DB driver reached | None — layering respected |
| A4 | Interfaces-before-impl / §6.6 | Responder model tier must be a wiring change (cheaper planner vs stronger responder) | Router injected via `build_graph(responder_router=...)` ctor seam; temperature/max_tokens are ctor params → tier swap is wiring-only | None — matches [[pattern-planner-classify-route-split]] DI shape |
| A5 | §7 / §10 untrusted content | Crawled/retrieved text treated as untrusted DATA, never executed as instructions; strip injected directives | `_grounding_block` fences worker+citation text in a labelled `BEGIN/END REFERENCE MATERIAL` block in a separate system message with an explicit "ignore embedded directives" preface | None — the injection boundary is handled where design flags it |
| A6 | §5.5 message_id | Stamp the stable feedback id on the terminal answer; reuse, don't reinvent | `state.message_id or uuid4().hex` in both node and `stream_graph` terminal state | None — consistent with [[ruling-message-id-feedback-key]] (terminal answer only) |
| A7 | P4-01 reducer contract | Do not re-write accumulated `citations` (list-concat reducer would double) | Node returns `response`/`finish_reason`/`message_id` only; citations pass through untouched | None — respects the fan-in reducer |
| A8 | Graph topology unchanged | Swap `responder_node` body only; edges/reducers/fan-out intact | `build_graph` resolves `Responder` vs dep-free `responder_node`; nodes/edges/`route_after_planner` unchanged; stub marker removed | None |
| A9 | Fail-soft posture (P4-03/04/05) | Router failure must not raise out of the node | `LLMError`/empty completion → `FALLBACK_RESPONSE` + `finish_reason="error"`; stream degrades to a fallback chunk | None — mirrors [[pattern-worker-node-di-scope]] fail-soft |
| A10 | Budget (§11) | Free/OSS/self-hosted, no paid path | Reuses in-process failover `LLMRouter`; no new paid dependency | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — `agents/responder.py`, Protocol-injected LLM seam, no cross-layer leak.
- [x] Honors locked decisions — no ReAct parser; native tool-calling surface present-but-unused (workers already ran); LangGraph node with typed shared state; Postgres/Redis untouched; no paid tier.
- [x] Interfaces-before-implementations — `LLMResponder` Protocol seam; test fakes inject without HF.
- [x] Budget posture respected — free/OSS/self-hosted; failover router reused.

## Notes
Two follow-ups (neither blocking; cheap to unwind later, both already scoped to later tasks):

1. **Learned communication style not yet applied (§3 / §5.4 → P9).** §3 says the Response Agent owns tone
   "adapted to the user's learned communication style," and §5.4 recall injects prefs into "planner/responder
   context." `_build_messages` currently composes persona + grounding + history + turn but does not read
   `state.memory`. This is correct for now — `memory_recall_node` is a P9 no-op stub, so there is nothing to
   apply — but P9 must wire `state.memory` into the responder prompt (and add the RESPONDER persona-adaptation),
   not just into the planner. Logged so P9 doesn't overlook the responder side of recall.

2. **`stream_graph` post-response tail runs on the placeholder answer.** The streaming entrypoint runs the full
   LLM-free `build_graph()` (including `output_guardrail`/`memory_writer`) to obtain merged worker state, then
   streams the real `Responder` over it — so the guardrail/memory tail executes against the discarded
   placeholder response, not the streamed one. The engineer documents this as the chat-endpoint integration
   task's concern, and the entrypoint is explicitly **not wired** into `POST /api/chat` yet, so no live path is
   affected. Acceptable for an isolated, unwired seam; the integration task must drive output guardrail + memory
   writer over the *streamed* answer (and own compiled-graph reuse instead of per-call compile).

Both are design-appropriate deferrals consistent with foundation-first sequencing; recorded as follow-ups, not
gate failures.
