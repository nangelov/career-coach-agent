---
name: pattern-verification-module-guard-scans
description: Phase-exit verification modules (test_pN_exit_verification.py) lean on source-string scans as "guard tests" — check they aren't defeated by nested parens / multi-line calls
metadata:
  type: project
---

The `backend/tests/test_pN_exit_verification.py` modules (P6-09/P7-05/P8-06 precedent) prove
cross-task consistency and frontend contracts with **source-string scans** rather than behavior.
Two recurring weaknesses to check, both usually **minor** (they live in verification-only test
code, not product):

**1. Naive-split guard scans.** e.g. P8-06's `test_only_dashboard_service_resolves_source_to_status`
scans `services/pdp_seed.py` / `tools/dashboard.py` by `src.split(".create_goal(")[1].split(")")[0]`
and asserts `"status=" not in call`. The `.split(")")[0]` truncates at the **first** `)`, which for a
multi-line `create_goal(user_id, GoalCreate(...), source=...)` closes the nested `GoalCreate(...)` —
so the scan never inspects args after the first nested paren. A `status=` placed on the `source=` line
would slip through. The paired `source=_AI_SOURCE in src` (whole-file) assertion still holds, so intent
survives — flag as a minor, not a blocker.

**2. Brittle frontend contract scans.** Approve/reject/guest-gate points are proven by exact-string
`in file` checks against `GoalCard.tsx` / `lib/dashboard.ts` / `Dashboard.tsx` (e.g.
`actions.updateGoal(goal.id, { status: APPROVE_STATUS.goal })`). They pass today but break on
harmless refactors. Acceptable given the behavioral proof lives in `frontend/__tests__/Dashboard.test.tsx`.

**How to apply:** don't gate on either; note them. The substantive check is whether the backend
points compose the **real** layered chain (router→service→store, planner→worker→tools→service,
real PdpService.generate) faking only LLM + DB sessions — that part has been genuine, not tautological.
