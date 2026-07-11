# Architecture review — P4-09-frontend-plan-citations · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Frontend structure / SoC (§8) | SSE transport stays thin & reusable, separate from the React view; mirrors backend Router→Service split | `lib/chatStream.ts` owns the wire union + parsing; `components/Chat.tsx` owns rendering only. `PlanEvent`/`SourceCitation` added to the transport, consumed by the component. Clean seam preserved | none |
| A2 | Wire contract fidelity (§9, P4-07) | Frontend types mirror backend `PlanEvent`/`SourceCitation`/`DoneEvent.citations` exactly, consume-only | `PlanEvent{intent:str, steps:str[], workers:str[]}` and `SourceCitation{source_id,title,url,snippet,worker: string|null}` match `backend/app/schemas/chat.py` (all `str|None`); `DoneEvent.citations` added. No backend edit | none |
| A3 | Visible thinking / worker steps (§3) | UI surfaces planner intent + which workers ran, per turn | `PlanIndicator` renders "Planning: <intent> → running <workers>" + step list, reusing the amber tool-step visual language; only when `workers.length>0` | none |
| A4 | Response Agent "cite sources" (§3) | Finished answer shows grounding sources, degrading per field | `CitationList`/`CitationEntry` render linked title when `url` present, else snippet/source_id; only when non-empty | none |
| A5 | Additive / no regression (P4-07 superset) | `tool_call`/`tool_result` and empty-plan/no-citation turns render exactly as before | Legacy tool-step handling untouched; plan strip and citation list both suppressed when empty (no stray boxes) | none |
| A6 | Defensive wire parsing | Tolerate missing/malformed fields (mirror `str(...)` convention) | `nullableStr`/`strArray`/`parseCitations` degrade non-array/missing to `[]`/null rather than throwing; unknown event names ignored forward-compatibly | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — transport/view separation held; frontend-only, no cross-layer leak into backend contract
- [x] Honors locked decisions — SSE streaming chat contract consumed as-is; no ReAct parser / Postgres+Redis / SSO / embeddings concerns in scope (frontend task)
- [x] Interfaces-before-implementations — `ChatStreamEvent` discriminated union remains the single seam the component depends on; new variants added the same way as `tool_call` precedent
- [x] Budget posture — N/A (no new deps/services; pure UI + parse)

## Notes
- Design-appropriate scope call: the plan strip is gated on `workers.length>0`, so a smalltalk turn's classified intent is not surfaced. This is intentional per the task non-goal ("no empty indicator boxes") and does not weaken §3 — visible thinking matters on turns that actually route to workers. Not a gap; logged for consistency.
- Citation `worker` field is parsed and carried but not rendered in the entry. Acceptable for this task's "simple inline list" non-goal; a future grouping-by-worker enhancement can use it without a contract change.
- No durable new design ruling — this consumes the already-blessed P4-06/P4-07 citations pass-through and SSE contract (see [[ruling-responder-p4-06-scope]]); nothing re-litigable here.

## Verdict: APPROVED
