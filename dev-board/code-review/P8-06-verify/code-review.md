# Code review — P8-06-verify · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/tests/test_p8_exit_verification.py:550 | The point-7 guard `test_only_dashboard_service_resolves_source_to_status` scans `create_*` calls via `chunk.split(")")[0]`, which truncates at the **first** `)` — for the multi-line `create_goal(user_id, GoalCreate(...), source=...)` that closes the nested `GoalCreate(...)`, so any `status=` placed after the first nested paren (e.g. on the `source=` line) is never inspected. The paired whole-file `source=_AI_SOURCE in src` assertion keeps the intent intact, so no real drift is missed today. | Optional: scan the full call span (balance parens or strip nested groups) so the `status=` guard covers args after a nested-paren argument. Non-blocking. |
| C2 | nit | backend/tests/test_p8_exit_verification.py:411-431, 515-517 | Frontend points 4 and 6 are proven by exact-string source scans against `GoalCard.tsx` / `lib/dashboard.ts` / `Dashboard.tsx`; brittle under harmless refactors. Acknowledged precedent (P7-05) and the behavioral proof lives in `frontend/__tests__/Dashboard.test.tsx`, so acceptable. | None required; noted. |

## Notes
Reviewed the new module against the real product code it drives (graph, dashboard_agent, tools/dashboard, services/dashboard, dashboard_store, pdp_seed) and ran it: **11 passed**. Frontend scan targets confirmed present in the current sources.

The tests genuinely compose the real chain and are **not** tautological or shallow:
- **Point 1/4/5(api)/6(api):** drive the real `/api/dashboard` router over `httpx.ASGITransport` → real `DashboardService` → `InMemoryDashboardStore` (a faithful double that mirrors the Postgres adapter's user-scoping + FK cascade/SET-NULL). Summary `time_progress_pct` / `task_completion_pct` / streak all computed by the **real** `get_summary` aggregation, not re-derived in the test.
- **Point 2:** runs the real compiled LangGraph (`build_graph`) with only the planner (test seam, a legit stand-in for the LLM classifier) and the LLM router faked; the propose lands via the **real** tool→registry→service→store path (`source="ai"` → service-resolved `status="proposed"`), and the "pending approval" language is produced by the real worker `_summarize` and carried into `state.response`. Only faked edge is the model.
- **Point 3:** exercises the **real** `PdpService.generate` (fence/forced-tool/parse/validate/seed) → `seed_dashboard_from_pdp` → real `DashboardService`; the regeneration de-dup (one goal, no dup milestones/tasks) is proven against the real title-match reuse rule, with `FreshSessionDBProvider` correctly modelling per-`session()` reads so the second `compute()` isn't starved.
- **Point 5(streak)/7:** real aggregation over a back-dated fixture; point 7's `_AI_PROPOSED_STATUS`-single-home + `source=_AI_SOURCE` assertions hold (modulo C1's scan gap).

Faked edges are only the true externals (LLM completions, DB sessions) per the P6-09/P7-05 posture. No product code changed. Acceptance criteria met: all 7 points covered by composed/integration-level tests, full backend + frontend suites reported green (focused module re-run here confirms), and the report states plainly that P8 meets the exit criterion with no P8-01..05 gaps — consistent with what the code shows.

Both findings are nits (verification-test-quality only); neither affects correctness of the conclusion.
