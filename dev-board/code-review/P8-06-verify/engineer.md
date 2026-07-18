# Engineer report — P8-06-verify · Revision 1

## Summary
Verified the **full P8 exit criterion** end-to-end — *"user edits a plan in the UI; assistant
proposes tasks from chat/PDP and the user approves; progress renders."* The per-task suites
(P8-01..05) each prove a piece in isolation (`test_dashboard_api` — CRUD router;
`test_dashboard_service` — policy/summary arithmetic; `test_dashboard_agent` — chat worker/graph;
`test_pdp_service` — the PDP loop; frontend `Dashboard.test.tsx` / `dashboard.test.ts` — the UI),
but **no single module composed the whole chain**: a human CRUD edit → the summary; a chat turn
through the compiled graph → an AI-proposed row; a real `PdpService.generate` → seeded proposals;
the approve/reject actions over the real API + the frontend wiring; the progress rollup; the guest
gate at every surface.

Added one cohesive verification-only module — `backend/tests/test_p8_exit_verification.py`
(11 tests, mirroring `test_p7_exit_verification.py`) — that drives the **real** dashboard chain,
faking only the true external edges (LLM completions, DB sessions), per the P6-09/P7-05 posture.

**Conclusion: the current P8 implementation MEETS the exit criterion as written.** All 7 task
points are covered (table below). **No gaps** found in P8-01..05. **No product code changed** —
verification-only. The point-7 cross-task consistency check confirms only
`DashboardService._resolve_status` maps `source→status`; the propose tools (P8-03) and the PDP
seed (P8-04) attribute AI writes with `source="ai"` and never re-implement the `proposed` status —
no drift to route back.

## Files changed
- `backend/tests/test_p8_exit_verification.py` — **new.** The composed P8 exit verification
  (11 tests). **No product code changed.**

## Key decisions
- **Compose the real chain; fake only external edges** (P6-09/P7-05 precedent). The chat point
  runs the real planner→dashboard-worker→tools→`DashboardService` over a scripted `LLMCompleter`;
  the PDP point runs the real `PdpService.generate` → agent → validate → `seed_dashboard_from_pdp`
  → real `DashboardService`; the CRUD/approval/progress points run the real `/api/dashboard` router
  over `httpx.ASGITransport`. Faked: the model, and the DB sessions.
- **Point 3 uses `FreshSessionDBProvider`.** The regeneration sub-case calls `PdpService.generate`
  twice, so the skills-gap `compute` re-reads the role profile a second time — a single shared
  `FakeSession` would be exhausted. A fresh empty role read per `compute()` models production's
  per-`session()` pooled connection and lets me prove the P8-04 de-dup rule (one goal, no duplicate
  milestones/tasks after regen) survives the P8-05 wiring.
- **Cross-stack points (4 frontend, 6 frontend) proven by source scan** — mirroring P7-05's
  section-header contract scans. `GoalCard.tsx` approves via `updateGoal/updateMilestone/updateTask`
  with `APPROVE_STATUS` and rejects via `deleteGoal/deleteMilestone/deleteTask`; `lib/dashboard.ts`
  maps those to `PATCH`/`DELETE` on the exact backend paths (no dedicated approve endpoint, per the
  P8-01/P8-02 ruling); `Dashboard.tsx` renders `GuestGate` for `session.role === "guest"`. The
  behavioral proof already lives in the frontend `Dashboard.test.tsx` (approve = PATCH→todo,
  reject = DELETE, guest gate, progress render) which runs green here.
- **Point 5 multi-day fixture is back-dated at the store edge.** A live `POST /progress` always
  stamps `now`, so a genuine multi-day streak can only be built by injecting back-dated entries at
  the store boundary (the fake port) and running the **real** `get_summary` aggregation over them —
  proving the streak/last-7 arithmetic, not a hand-rolled copy. The API POST→GET wiring is proven
  separately with today's entries.
- **Point 7 is a guard test, not a fix.** It asserts `_AI_PROPOSED_STATUS = "proposed"` is defined
  only in `services/dashboard.py`, and that `tools/dashboard.py` + `services/pdp_seed.py` issue
  their `create_*` calls with `source=_AI_SOURCE` and **no** `status=` argument. No drift found, so
  nothing to route back.

## P8 exit criterion — point-by-point
| # | Task point | Where proven |
|---|-----------|--------------|
| 1 | User edits a plan directly → correct summary | `test_user_edits_plan_directly_and_summary_is_correct` (real API POST/PATCH; `source="user"`; nesting; `task_completion_pct==50`; in-range non-null `time_progress_pct`) |
| 2 | Assistant proposes from chat (pending, never silent) | `test_assistant_proposes_from_chat_lands_proposed_and_says_pending` (compiled graph; row `source="ai"`/`status="proposed"`; responder answer says proposed + pending approval) |
| 3 | Assistant proposes from PDP + regen de-dup | `test_pdp_generation_seeds_proposed_rows_and_regeneration_does_not_duplicate` (real `PdpService.generate` seeds `proposed` goal/milestones/tasks; regen → still one goal, no dup rows) |
| 4 | Approval flow (approve=PATCH, reject=DELETE) | `test_approve_and_reject_proposed_rows_over_the_api` (real API) + `test_frontend_approve_reject_target_the_same_verbs_and_endpoints` (source scan of `GoalCard.tsx` + `lib/dashboard.ts`) + frontend `Dashboard.test.tsx` |
| 5 | Progress renders | `test_progress_entries_feed_the_summary_over_the_api` (POST→GET wiring) + `test_progress_summary_multi_day_streak_arithmetic` (real aggregation over a multi-day fixture) + frontend `Dashboard.test.tsx` `ProgressPanel` render |
| 6 | Guests correctly excluded | `test_guest_is_rejected_across_the_api_surface` (403) + `test_guest_chat_turn_fails_soft_without_calling_the_model` (no model call, no write, sign-in message) + `test_frontend_gates_guests_with_a_sign_in_prompt` (source scan) |
| 7 | Cross-task attribution consistency | `test_only_dashboard_service_resolves_source_to_status` (resolver defined only in the service; AI-write callers pass `source=_AI_SOURCE`, never `status=`) |

## Gaps flagged in prior P8 tasks
**None.** All P8-01..05 behaviours needed by the exit criterion hold, and the source→status
attribution is resolved in exactly one place. No product code changed and no live-infra check was
needed here (the dashboard chain's only DB touches — role-profile read in P8-04 and the store
snapshot — are already covered against live Postgres by `test_dashboard_store_postgres` /
`test_pdp` suites; this module fakes those sessions to keep the P8 chain the unit under test).

## How to verify
```bash
# Backend (from backend/) — mirrors `make check`:
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy app/ migrations/
uv run --no-sync pytest -q                                   # offline (live-DB tests skip)
uv run --no-sync pytest tests/test_p8_exit_verification.py -q  # focused
# Frontend (from frontend/) — mirrors frontend-ci.yml:
npm run lint && npm run type-check && npm test -- --watchAll=false
```

## Tests (final step — mandatory)
- `ruff check .` → **All checks passed!**
- `ruff format --check .` → **232 files already formatted.**
- `mypy app/ migrations/` → **Success: no issues found in 139 source files**; new test file mypy
  → **Success: no issues found in 1 source file**.
- `pytest -q` → **730 passed, 62 skipped** (+11 new; the 62 skips are the pre-existing live-DB
  `*_postgres` integration tests — no Postgres in this run, unrelated to this task).
- Focused: `pytest tests/test_p8_exit_verification.py -q` → **11 passed**.
- Frontend: `npm run lint` → **No ESLint warnings or errors**; `npm run type-check` (`tsc --noEmit`)
  → clean; `npm test` → **20 suites, 191 passed**.
- No failing tests. No test weakened or deleted; no product code changed.

## Self-check
- [x] Meets acceptance criteria — all 7 P8-06 points covered by composed/integration-level tests;
  the one live-infra choice (no live Postgres) is documented above; full backend `make check`
  scope + full frontend suite all green; report states the criterion **is met** and confirms no
  P8-01..05 gap.
- [x] No secrets committed; verification-only (no product-code logic changed); Router→Service→
  Agent/Repo layering respected (the tests drive the real layered stack, faking only the LLM + DB
  edges).
- [x] Tests/lints pass (results pasted above).
