# Architecture review — P8-06-verify · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Phase-exit verification posture | (T) verify: real stack, fake only outer edges, no product-code change; prove whole chain, report yes/no on the exit criterion (P6-09/P7-05 precedent) | One new module `backend/tests/test_p8_exit_verification.py` (11 tests) composing the real dashboard chain; only the LLM completer + DB sessions are faked; `git status` confirms it is the sole file this task adds and no product code is touched | none |
| A2 | §8 target structure | test lives under `tests/`; exercised product code sits in `api/`, `services/`, `agents/`, `tools/`, `schemas/`, `repositories/` | Verification is a test-only module; it drives `api/dashboard.py`, `services/dashboard.py` + `pdp*`, `agents/graph`, `tools/dashboard.py`, `schemas/dashboard.py` in place | none |
| A3 | Layering Router→Service→Agent/Repo | tests drive the real layered stack through the router / compiled graph, not around it | API points go through `/api/dashboard` over ASGITransport; chat points through the compiled `build_graph`; PDP through real `PdpService.generate`; only model + session edges faked | none |
| A4 | §5.2 AI writes = proposed→approve, never silent | AI writes land `source="ai"`/`status="proposed"`; responder frames as pending; approve=PATCH, reject=DELETE (no dedicated endpoint per P8-01/02) | Points 2,3,4 assert exactly this end-to-end (backend API + graph + PDP seed) and the frontend source scan confirms `GoalCard`/`lib/dashboard.ts` hit the same generic verbs/paths | none |
| A5 | §5.2 guests excluded (needs an account) | API 403s; chat worker fails soft without a model call; frontend sign-in gate | Point 6 proves all three surfaces (403 across API, `router.calls == 0` + "account" fail-soft, `GuestGate` scan) with no raw crash | none |
| A6 | DRY / SoC — single source→status resolver (P8-02) | `_resolve_status` in `services/dashboard.py` is the only place mapping source→status; AI-write callers pass `source=` only | Point 7 guard asserts `_AI_PROPOSED_STATUS` defined only in the service and that `tools/dashboard.py` + `services/pdp_seed.py` never pass `status=`; no drift found | none |
| A7 | §5.2 progress rendering | POST entries feed `GET /api/dashboard` summary; streak/last-7 arithmetic correct via real aggregation | Point 5 proves API POST→GET wiring plus real `get_summary` streak arithmetic over a back-dated multi-day fixture | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — verification-only, drives the real stack
- [x] Honors locked decisions — LangGraph compiled graph + native tool-calls (`ToolCall`/`FunctionCall`, no ReAct parser); no new datastore; SSO/`require_auth`-gated; guest exclusion enforced
- [x] Interfaces-before-implementations — fakes injected at the real seams (`LLMCompleter`/router, DB providers, in-memory stores), product code untouched
- [x] Budget posture respected — no live infra required beyond what is already covered; offline run (live-DB tests skip)

## Notes
- Sound phase-fit: scope stays within P8 and re-verifies P8-01..05 as a composed chain rather than re-running isolated suites; matches the P7-05 shape.
- Back-dating progress at the store edge (point 5) is the correct way to exercise multi-day streak arithmetic given a live POST always stamps `now` — it runs the real aggregation, not a hand-rolled copy. Acceptable.
- Cross-stack points 4/6 lean on source scans for the frontend contract, backed by the behavioral `Dashboard.test.tsx`; consistent with the P7-05 contract-scan precedent — acceptable, not a hollow assertion.
- Engineer reports no gaps in P8-01..05 and the guard test substantiates the single-resolver claim; nothing to route back.
