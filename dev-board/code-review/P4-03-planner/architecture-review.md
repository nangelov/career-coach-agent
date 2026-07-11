# Architecture review — P4-03-planner · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Planner lives at `backend/app/agents/planner.py` | New `app/agents/planner.py`; exports added to `app/agents/__init__.py` | none |
| A2 | §3 Planner | classify intent (chat/job_search/pdp/cv_question/smalltalk), decompose into steps, route to workers, set iteration/token budget | `Planner.plan` produces full `PlannerDecision(intent, steps, workers, max_iterations)`; `token_budget` left `None` (provider default, optional per task) | none |
| A3 | §6 item 2 / §6.6 (locked) | native tool-calling, **no ReAct text parser** | Single JSON-schema tool `record_plan` with `tool_choice` pinned to it; parses `ToolCall.function.arguments`; no free-text/ReAct path | none |
| A4 | §3 fan-out | intent → worker mapping drives `route_after_planner` | Deterministic `_INTENT_WORKERS` (`job_search→[JOB_SEARCH]`, `pdp→[PDP_RESUME]`, `cv_question→[RAG]`, `smalltalk→[]`, `chat→[RAG]` iff `needs_grounding`); LLM classifies, code routes | none — classification/routing split is the conservative, testable choice while workers are still stubs |
| A5 | Layering (Router→Service→Agent) | agent depends on LLM router surface, not a DB driver or provider SDK | `Planner` takes an `LLMCompleter` `Protocol` structurally matching `LLMRouter.complete`; imports only `app.agents.state`, `app.llm.errors`, `app.llm.types` | none |
| A6 | §6.6 planner model tier | don't hardcode a client; keep cheaper/faster-planner-model option open | Router injected by constructor, not hand-rolled; swapping tiers is a `build_graph(router=...)` wiring change | none |
| A7 | Graph contract (P4-02) | topology / `route_after_planner` / `PLANNER` node / conditional-edge wiring unchanged; only the decision producer swaps | `[STUB → P4-03]` marker removed; `build_graph` gains additive `router=` seam; edges/nodes/`route_after_planner` untouched; `AgentState` + reducers untouched | none |
| A8 | Fail-soft (task acceptance) | router error / malformed tool call → safe default, never raise out of the node | `except LLMError` → `_safe_default_decision`; `_parse_decision` returns `None` on missing/invalid/unknown-intent args → safe default; node never raises | none — `LLMError` is the router's documented failure contract (all failover errors subclass it); catching that precise class rather than bare `Exception` is correct |
| A9 | Phase fit (P4) | do not implement real workers, do not wire into `POST /api/chat` | Workers stay stubs; module-level `graph` still builds with the no-router fallback; chat wiring deferred | none |
| A10 | Budget posture (§11) | free/OSS/self-hosted, no new paid deps | No new dependencies; reuses existing LLM primitives | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — planner sits in `agents/`, depends only on the LLM vocabulary/router surface via a Protocol.
- [x] Honors locked decisions — native forced tool-calling, no ReAct parser; no datastore coupling; nothing that violates Postgres+Redis / SSO / in-process-embeddings decisions.
- [x] Interfaces-before-implementations — `LLMCompleter` Protocol is a real seam (mirrors `LLMRouter.complete` exactly), so router/model tier is swappable; tool schema reuses the P1-03 `ToolSchema` convention rather than inventing a parallel one.
- [x] Budget posture respected (free/OSS/self-hosted) — no paid or new deps.

## Notes
- Minor (non-blocking, cheap to fix later): two safe-default paths use different `max_iterations` for a `chat` turn — `graph.planner_node` (no-router default) relies on `PlannerDecision`'s field default `5`, while `planner._safe_default_decision()` uses `_INTENT_MAX_ITERATIONS[Intent.CHAT] == 3`. Both are safe; only a cosmetic inconsistency. Worth aligning when the chat endpoint injects the real router (the no-router `planner_node` becomes import-time-only scaffolding at that point).
- Follow-up for P4-04..P4-06: those tasks inherit this classification-vs-routing split. Any new worker routing must extend `_INTENT_WORKERS` / `_workers_for` deterministically rather than letting the model emit node names — keep the seam.
- `_memory_note` already folds `state.memory.memories` into the planner prompt; harmless no-op until P9 populates it, and correctly positioned for the P9 recall→planner personalization path (§3, §5.4).
