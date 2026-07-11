# Architecture review — P4-01-agent-state · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | `agents/state.py` — shared typed state (design line 351) | `backend/app/agents/state.py` created + exported from `agents/__init__.py` | none |
| A2 | §3 state shape | Typed **Pydantic** object holding user/session ids, history slice, planner decisions, per-worker results, citations, safety verdicts | `AgentState(BaseModel)` carries `session_id`/`user_id`/`role`, `history: list[ChatMessage]`, `plan: PlannerDecision`, `worker_results`, `citations`, `input_safety`/`output_safety` — all six §3 elements present | none |
| A3 | Pydantic-vs-TypedDict | §3 explicitly says "typed object (Pydantic)" | `BaseModel` chosen (documented) over TypedDict; still LangGraph-compatible via `Annotated` reducers | none — matches locked decision literally |
| A4 | §3 Planner | classify intent, decompose steps, route to workers, set iteration/token budget | `PlannerDecision`: `intent: Intent`, `steps`, `workers: list[WorkerName]`, `max_iterations`, `token_budget` | none |
| A5 | LangGraph orchestration (locked) | State composes with `StateGraph` reducers so parallel workers don't clobber | `worker_results: Annotated[dict, merge_worker_results]` (key-wise), `citations: Annotated[list, operator.add]`; single-writer fields carry no reducer; proven by a real `StateGraph` fan-out test | none — the flagged main technical risk is handled correctly |
| A6 | Reuse existing vocabulary (no parallel copies) | Reuse P1 message shape, P3 identity types, P2 id bounds | `role: SessionRole` (verbatim from `app.schemas.auth`), `history: list[ChatMessage]` + `message_id` (from `app.llm.types`, P1/§5.5), `session_id/user_id` `max_length=64` mirrors `SessionRecord`/`String(64)` | none |
| A7 | §3 memory recall / §5.4 | Recall feeds prefs + learned memories before planning (reserved for P9) | `memory: MemoryContext` with `preferences` + `memories` slots, unused until P9 | none |
| A8 | §3/§7 guardrails (reserved for P10) | Pre + post safety verdict shape must exist now | `SafetyVerdict` with `stage`/`allowed`/`categories`/`reason`; `input_safety`/`output_safety` fields default-open | none |
| A9 | §4 data ownership | Guests nullable/Redis-only; user-scoped | `user_id: str \| None` (None for guests), `role` defaults `"guest"`; pure state module touches no store | none |
| A10 | Phase fit / non-goals | State-only; no graph.py, planner, workers, responder, guardrail/memory logic | Only state + supporting enums/sub-models + reducer; no node wiring; new module unused until `graph.py` lands | none — scope respected |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — pure state/vocabulary layer; no DB drivers, services, or cross-layer leaks.
- [x] Honors locked decisions — LangGraph typed shared state; no ReAct parser reintroduced; Postgres+Redis untouched; SSO-only identity vocabulary reused (`SessionRole`), no passwords.
- [x] Interfaces-before-implementations — state is a stable seam consumed by later P4 nodes; reducers are the real fan-in contract `graph.py` depends on.
- [x] Budget posture respected — free/OSS only; in-process, no paid dependency introduced.

## Notes
- Design risk (low): `WorkerName` enumerates RAG/WEB_SEARCH/JOB_SEARCH/PDP_RESUME and omits a "responder" member because the Response Agent is modeled as the single-writer `response`/`finish_reason` fields rather than a keyed worker slice. Consistent with §3 (responder synthesizes, is not a fan-out worker). No change needed; later P4 tasks should keep the responder out of `worker_results`.
- `worker_results` is typed `dict[str, WorkerResult]` and keyed by `WorkerName` (a `StrEnum`, so a `str`). Consistent and JSON-safe; later nodes should key by `WorkerName` for uniformity (tests already do).
- Follow-up (P9/P10, not blocking): when memory-recall and guardrail logic land, they write into the reserved `MemoryContext` / `SafetyVerdict` slots — confirm they don't reshape the state contract, only populate it.
- JSON round-trip via `model_dump_json`/`model_validate_json` is a genuine seam for the Redis/Celery memory-writer boundary (§3, async) — good forward-looking coverage.
