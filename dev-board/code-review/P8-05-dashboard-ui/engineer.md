# Engineer report — P8-05-dashboard-ui · Revision 1

## Summary
Built the Next.js living-PDP dashboard UI over the P8-02 API: an `/api/dashboard` client module,
the `/dashboard` route (guest → sign-in gate, no raw 403), the goals/milestones/tasks board with a
progress/streak panel and % to target-date bars, and the approve/reject surface for AI-proposed
rows. No backend changes. Mirrors the existing roles/profile/pdp frontend slice conventions exactly.

## Files changed
- `frontend/lib/dashboard.ts` (new) — pure API-client for the whole `/api/dashboard` surface:
  wire types mirroring the backend Pydantic schemas verbatim (snake_case), `DashboardApiError`
  carrying HTTP status, defensive `raw → typed` parsers, injectable `fetchImpl`/`baseUrl` (DI, no
  client auth header). Functions: `getDashboardSummary`, `createGoal`/`updateGoal`/`deleteGoal`,
  `createMilestone`/`updateMilestone`/`deleteMilestone`, `createTask`/`updateTask`/`deleteTask`,
  `addProgress`/`listProgress`, plus `APPROVE_STATUS` (the status a proposed row is approved into).
- `frontend/components/Dashboard.tsx` (new) — the board: guest `GuestGate` (mirrors `PdpGenerator`),
  summary fetch + refresh-after-mutation, `DashboardActions` write surface, grouped goal columns
  (proposed / active / completed+archived), the progress/streak panel, create-goal form,
  load/empty/error + per-action error states.
- `frontend/components/dashboard/GoalCard.tsx` (new) — a goal card: % to target-date +
  task-completion bars (plain CSS), nested milestone/task rows, "Proposed by your coach" badge with
  Approve (PATCH off `proposed`) / Reject (DELETE), complete/delete, add-milestone/add-task inline
  forms, log-progress.
- `frontend/components/Chat.tsx` — added the "Dashboard" nav link alongside Roles/Profile/Plan.
- `frontend/app/dashboard/page.tsx` (new) — the route: session hydration via `fetchSession()`,
  `Login` when unauthenticated, "Back to chat" header, renders `<Dashboard>`.
- `frontend/__tests__/dashboard.test.ts` (new) — client unit tests with an injected fake `fetchImpl`.
- `frontend/__tests__/Dashboard.test.tsx` (new) — component tests over a mocked API client
  (guest gate, progress/% render, approve/reject/create/add-task/log-progress, load + action errors).

## Key decisions
- **Approve = PATCH off `proposed`, reject = DELETE** (§5.2; backend `GoalUpdate`/`*Update` exclude
  `proposed`). `APPROVE_STATUS` maps goal→`active`, milestone→`pending`, task→`todo` — the ORM
  server defaults from `services/dashboard.py::_USER_DEFAULT_STATUS`.
- **Refresh-after-mutation** rather than optimistic local edits: every write re-fetches
  `GET /api/dashboard` so the server-computed `time_progress_pct` / `task_completion_pct` / streak
  stay authoritative (P8-02 computes them; reconstructing client-side would drift).
- **Guest handling inside the component** (a sign-in gate that preserves the session via
  `upgradeGuestToSso`), mirroring `PdpGenerator`'s `GuestGate` — not a raw 403 (§5.2).
- **No charting library** — plain CSS/SVG bars, per the task and the frontend's zero-heavy-dep
  posture (`package.json` unchanged).
- **No analytics wiring** — there is no GA4/`gtag` convention anywhere in the frontend (grep clean),
  so the task's conditional "if the app fires interaction events" does not apply; nothing invented.
- **Nav link only in `Chat.tsx`** — that is the single primary-nav location in the app; other pages
  only carry a "Back to chat" link, so the Dashboard page mirrors that (back-link present).

## How to verify
- `cd frontend && npx tsc --noEmit && npm run lint && npm test`.
- Manually: chat header → "Dashboard"; a guest sees the sign-in gate; a user sees the board,
  can add a goal/milestone/task, approve/reject a proposed row, complete/delete, and log progress.

## Tests (final step — mandatory)
- `npx tsc --noEmit` → clean.
- `npm run lint` → "No ESLint warnings or errors".
- `npm test` → **20 suites, 191 tests, all passing** (26 new: `dashboard.test.ts` +
  `Dashboard.test.tsx`). No failures; nothing to root-cause.

## Self-check
- [x] Meets acceptance criteria (client fns + unit tests; `/dashboard` guest gate vs board;
      approve/reject via real endpoints in a component test; % + streak render; nav link;
      lint/tsc/test green).
- [x] No secrets committed; layering respected (thin DOM-light client → route → component; no client
      auth token — BFF injects it server-side).
- [x] Tests/lints pass (pasted above).
