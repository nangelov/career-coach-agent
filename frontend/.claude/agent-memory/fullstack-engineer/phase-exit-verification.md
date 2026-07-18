---
name: phase-exit-verification
description: How to build a P*-verify phase-exit task — compose the real chain, fake only LLM+DB edges, mirror the prior P*-05 module
metadata:
  type: feedback
---

A `P<n>-*-verify` phase-exit task is verification-only (no product-code logic change). Build one
`backend/tests/test_p<n>_exit_verification.py` that composes the whole chain end-to-end and reports
a clear yes/no on the plan.md exit criterion — do NOT just re-run per-task suites.

**Why:** reviewers gate on "prove the whole chain, not pieces in isolation" (P6-09/P7-05 precedent),
and on the same fake posture every time.

**How to apply:**
- Fake ONLY the true external edges: the LLM (`_ScriptedCompleter` returning native tool-calls, one
  per `complete`) and the DB sessions (`FakeSession`/`FakeDBProvider` from `tests.fakes`). Everything
  between (services, tools, graph, router) is the real object.
- If a flow re-runs a DB read (e.g. PDP regeneration calls `skills_gap.compute` again), a single
  shared `FakeSession` is exhausted after the first call — use `FreshSessionDBProvider(lambda: FakeSession([...]))`.
- Drive chat turns through `build_graph(planner=<fn returning PlannerDecision>, ...)` + `compiled.ainvoke`;
  drive HTTP via `httpx.AsyncClient(ASGITransport(app))` + `app.dependency_overrides` (clear in a fixture teardown).
- Cross-stack/contract points allow a source-scan test (read the frontend `.tsx`/`.ts` and assert the
  exact verbs/endpoints/symbols), mirroring P7-05's section-header scans — legitimate, not brittle-flagged.
- Planner-function param to `build_graph` must be typed `-> Any` (langgraph node type mismatch else).
- Final: `make check` scope must be green — `ruff check .`, `ruff format --check .`, `mypy app/ migrations/`
  + the new test file, `pytest -q` (live-Postgres `*_postgres` tests skip offline), and the full frontend
  suite (`npm run lint`, `npm run type-check`, `npm test -- --watchAll=false`).
