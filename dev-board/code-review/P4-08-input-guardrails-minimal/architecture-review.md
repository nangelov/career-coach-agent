# Architecture review — P4-08-input-guardrails-minimal · engineer revision 1

## Verdict: APPROVED

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Guardrail code lives in reserved `backend/app/guardrails/` | New `app/guardrails/heuristics.py` (`screen_input`, `REFUSAL_MESSAGE`) + `__init__.py` re-export; graph imports from `app.guardrails` | None — correct module placement |
| A2 | §7 input guardrails | Jailbreak / prompt-injection detection *before content hits tools or external APIs* | Blocked turn short-circuits `INPUT_GUARDRAIL → OUTPUT_GUARDRAIL → MEMORY_WRITER → END`, skipping planner/workers/responder; no tool/API/LLM call runs for a blocked turn | None — content genuinely never reaches workers |
| A3 | §3 graph topology | `Guardrails(input) → Memory recall → Planner → workers → Responder → Guardrails(output) → Memory writer` | Static `INPUT_GUARDRAIL→MEMORY_RECALL` edge replaced by a conditional edge over `[MEMORY_RECALL, OUTPUT_GUARDRAIL]`; all other P4-02 edges (fan-out/fan-in/output/writer) untouched | None — change is localized to the input-guardrail outgoing edge, as the task scoped |
| A4 | Interfaces-before-implementations | Guardrail is a real seam P10 swaps wholesale | `screen_input(message) -> SafetyVerdict(stage=INPUT)` is the stable contract; graph routes on the returned verdict via `route_after_input_guardrail`; P10 replaces detection without touching graph wiring | None — clean seam; deny-list documented as placeholder |
| A5 | AgentState immutability (task constraint / P4-01) | No `AgentState`/`SafetyVerdict`/`GuardrailStage` shape or reducer change | Reuses existing `SafetyVerdict`; only writes `input_safety`/`response`/`finish_reason`/`message_id` (all pre-existing fields) | None |
| A6 | Layering (Router→Service→Agent/Repo) | Heuristic is a leaf; graph routes on it; service unchanged | Heuristic is a pure leaf function; `ChatService` needs no change (blocked turn → `plan is None` → no `PlanEvent`, refusal chunk → normal `done`) | None |
| A7 | Budget posture (§11) | Free / OSS / self-hosted; no paid dependency | Pure `re` regex; no LLM call, no ML model, no network, no new dependency | None |
| A8 | Phase fit | Minimal slice now; full classifier P10 | Small documented deny-list, default-open, explicitly marked P10-replaceable; PII/abuse/off-topic correctly deferred | None — no premature coupling to P10 |
| A9 | §5.5 feedback id | Terminal answer carries a stable `message_id` | Blocked-turn refusal reuses `state.message_id` (mints only if unset), consistent with the responder/planner-node convention | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — heuristic in `app/guardrails/`, graph routes, service untouched.
- [x] Honors locked decisions — LangGraph orchestration extended via a conditional edge (no hand-rolled control flow); no ReAct parser; no new datastore; deterministic, no LLM.
- [x] Interfaces-before-implementations — `screen_input -> SafetyVerdict` seam; P10 swaps detection only.
- [x] Budget posture respected — regex-only, no paid/API/model cost.

## Notes
- **Block routes to `OUTPUT_GUARDRAIL`, not `RESPONDER` — blessed.** The task left the target node to the engineer's call; routing to the terminal tail (rather than RESPONDER) is the correct choice for the split-phase streaming design: the real answer is streamed *separately* by `GraphTurnStreamer.stream_response`, which would discard a pre-graph RESPONDER placeholder anyway. Routing to `OUTPUT_GUARDRAIL` skips planner + responder while still running the output-guardrail + memory-writer tail, so the refusal even passes through the (future) output guardrail — defense in depth.
- **Consistency with the P4-06/P4-07 streaming-tail ruling.** For a *blocked* turn the canned refusal is stamped into `response` during `plan()` (the pre-responder graph), so the output-guardrail/memory-writer tail runs over the *actual* final text, not a discarded placeholder. This does not conflict with the standing P9/P10 enforcement note (that the post-response path must be restructured to run over the *streamed* answer) — that note targets the *allowed* streamed path; the blocked path has no streamed LLM answer to reconcile. When P10 lands the real output guardrail, blocked turns are already correct; the allowed streamed path remains the item to restructure.
- Deny-list breadth is a detection-quality concern (code-reviewer's domain), not a design-conformance one. From a design standpoint the default-open posture and the small, swappable list are exactly the minimal-slice shape the task and §7 intend.

## Verdict: APPROVED
