# Task P8-06-verify — P8 exit: user edits plan; assistant proposes tasks; approval flow; progress renders
- **Phase:** P8   **Status:** ENG   **Tags:** (T)
## Scope
tasks.md item: *"User edits plan; assistant proposes tasks; approval flow; progress renders."*
Plus the phase exit criterion (`dev-board/plan.md` Phase 8): *"user edits a plan in the UI;
assistant proposes tasks from chat/PDP and user approves; progress renders."*

This is the phase-level integration verification pulling together P8-01 (schema),
P8-02 (`api/dashboard.py` CRUD + summary), P8-03 (native dashboard tools in the chat graph),
P8-04 (PDP seeding) and P8-05 (frontend UI). Mirror how `P6-09-manual-verify` /
`P7-05-verify` composed their phase-exit verification (read
`dev-board/code-review/P7-05-verify/task.md` + `engineer.md` for the expected shape/rigor) —
don't just re-run each prior task's own suite in isolation; prove the **whole chain**
end-to-end and report a clear yes/no on the P8 exit criterion.

Specifically verify (automated tests / composed integration tests preferred — "real stack,
in-memory/fake ports, no live HF/live Postgres" per the P4-10/P6-09/P7-05 precedent; note
plainly anywhere a check genuinely needs live infra this environment lacks):

1. **User edits a plan directly** — a human `POST/PATCH/DELETE` through `/api/dashboard/...`
   creates/edits/completes a goal/milestone/task with `source="user"`, independent of any AI
   involvement, and it shows up in `GET /api/dashboard`'s summary (nesting, `time_progress_pct`,
   `task_completion_pct` all correct for a hand-built fixture scenario).
2. **Assistant proposes tasks from chat** — drive a chat turn through the compiled graph
   (`app.agents.graph`, fake `LLMCompleter`/router seam per the existing agent test style) whose
   planner classifies `Intent.DASHBOARD` and the dashboard worker (P8-03) calls a propose tool;
   confirm the resulting row lands `source="ai"` / `status="proposed"` and the responder's answer
   tells the user it's pending review (never silently active).
3. **Assistant proposes tasks from a generated PDP** — drive `PdpService.generate` (P8-04, fake
   ports) end-to-end and confirm the seeded goal/milestones/tasks land `source="ai"` /
   `status="proposed"`, and that regenerating the same career goal does not duplicate the goal
   (P8-04's de-dup rule still holds after P8-05 wiring — no regression).
4. **Approval flow** — a `PATCH` moving a `proposed` row to its normal status (the "approve"
   action, no separate endpoint per P8-01/P8-02's ruling) and a `DELETE` of a `proposed` row (the
   "reject" action) both work end-to-end via the API, and the P8-05 frontend's approve/reject
   client calls hit exactly those endpoints (confirm against `frontend/lib/dashboard.ts` +
   `frontend/components/dashboard/GoalCard.tsx`, not just the backend).
5. **Progress renders** — `POST /api/dashboard/progress` entries feed `GET /api/dashboard`'s
   `progress` summary (`total_entries`, `entries_last_7_days`, `current_streak_days`,
   `last_entry_date`) correctly for a multi-day fixture scenario, and the P8-05 UI renders that
   summary (component test, mocked client — confirm it's wired, not just present in the API).
6. **Guests correctly excluded** — every dashboard surface (API + UI) rejects/gate a guest
   (`user_id is None`) per §5.2 "dashboard requires an account", with no raw crash anywhere in
   the chain (router 403s, chat worker fail-soft message, frontend sign-in gate).
7. **Cross-task consistency check** — grep for any place that re-implements the
   `source`/`status` attribution resolution instead of going through
   `DashboardService._resolve_status` (P8-02) — flag any drift as a gap for the owning task, do
   not silently fix it here.

## Acceptance criteria
- [ ] All 7 points above are covered by automated tests (composed/integration-level where prior
      per-task tests only proved pieces in isolation) or a clearly documented reason something
      requires live infra this environment doesn't have.
- [ ] Full backend test suite green (`ruff check`, `ruff format --check`, `mypy`, `pytest`) and
      full frontend test suite green (`eslint`, `tsc --noEmit`, `jest`) — pre-checks for P8-07,
      not a substitute for it, but don't leave either red here.
- [ ] Report states clearly: does the current P8 implementation meet the phase exit criterion?
      If a gap is found in any prior P8 task's work (P8-01..05), flag it precisely (which task,
      what's missing) rather than silently patching around it, so the orchestrator can route a
      fix to the right task.

## Design references
- `dev-board/plan.md` — Phase 8 exit criterion.
- `dev-board/app-design-and-features.md` §5.2 (Dashboard — the living Personal Development Plan).
- Precedent: `dev-board/code-review/P7-05-verify/`, `dev-board/code-review/P6-09-manual-verify/`.
