# Task P8-05-dashboard-ui — Dashboard frontend UI
- **Phase:** P8   **Status:** ENG   **Tags:** (F)
## Scope
tasks.md P8 item: "Dashboard UI: goals/tasks board, progress charts/streaks, % to target date;
approve/reject AI proposals."

Build the Next.js UI for the living-PDP dashboard over the P8-02 API
(`GET /api/dashboard`, `/api/dashboard/goals|milestones|tasks|progress`) and the P8-03/P8-04
propose→approve workflow (AI-proposed rows carry `status="proposed"` / `source="ai"`; approving
is a `PATCH` moving `status` off `proposed`, rejecting is a `DELETE`).

**Follow the existing frontend conventions exactly** (mirror `lib/roles.ts` + `app/roles/page.tsx`
+ `components/RoleRequirements.tsx`, and `lib/profile.ts` + `components/ProfileView.tsx` for the
CRUD-with-edit-forms shape):
- `lib/dashboard.ts` — a pure API-client module: injectable `fetchImpl`/`baseUrl` (DI for tests,
  no hard globals), no client-side auth (the BFF injects `Authorization` server-side from the
  httpOnly cookie, SEC-04 — this layer never touches a token), wire types mirroring the backend
  Pydantic schemas verbatim (snake_case), a typed `DashboardApiError` carrying the HTTP status
  (mirror `RolesApiError`/`ProfileApiError`), and defensive `raw: unknown → typed` parsing
  (mirror `parseRoleRequirements` etc. — never trust the wire shape blindly).
- `app/dashboard/page.tsx` — the route: hydrate the session via `fetchSession()` (mirror
  `app/roles/page.tsx`), show `Login` if unauthenticated. **Guests are rejected** (§5.2:
  "dashboard requires an account") — reuse `UpgradePrompt`-style guest messaging (a guest sees an
  "sign in to save a living plan" prompt with SSO buttons, not a raw 403), not the chat's
  rate-limit flavor of that component specifically, but the same sign-in-with-preserved-session
  affordance.
- `components/Dashboard.tsx` (+ any sub-components you find natural, e.g.
  `components/dashboard/GoalCard.tsx`) — the board itself.
- Add a "Dashboard" nav link alongside the existing "Roles" / "Profile" / "Plan" links in
  `components/Chat.tsx`'s header (and `app/roles/page.tsx` / wherever else those links repeat) →
  `/dashboard`.

**UI requirements (task acceptance / design §5.2):**
- **Goals/tasks board:** list goals (grouped, e.g. active vs. proposed vs. completed), each
  showing its milestones and tasks; create/edit/complete a goal, milestone, task (human writes —
  `source="user"`, which the backend router already enforces regardless of what the client sends).
- **Progress charts/streaks:** render the `GET /api/dashboard` summary's `progress` block
  (`total_entries`, `entries_last_7_days`, `current_streak_days`, `last_entry_date`) — a simple,
  honest rendering (e.g. a streak counter + a small bar/sparkline of recent activity) is enough;
  do not pull in a charting library for a first cut — plain CSS/SVG bars are fine and match the
  app's no-heavy-frontend-deps posture so far (check `frontend/package.json` before adding one).
- **% to target date:** render each goal's `time_progress_pct` / `task_completion_pct` from the
  summary (already computed server-side, P8-02) as a simple progress bar.
- **Approve/reject AI proposals:** any goal/milestone/task with `status="proposed"` (and,
  correspondingly, `source="ai"`) is visually distinct (e.g. a badge: "Proposed by your coach")
  with **Approve** (PATCH the row to its normal starting status — `active`/`pending`/`todo`) and
  **Reject** (DELETE the row) actions. This is the "never silent" UX surface (§5.2).
- **Log progress:** a simple "log progress" action (optionally tied to a goal/task) posting to
  `/api/dashboard/progress`.
- Loading/empty/error states (mirror `RoleRequirements.tsx` / `ProfileView.tsx` patterns);
  network errors surface the backend's `detail` message via `DashboardApiError`, not a raw stack.

**Consent / analytics (existing cross-cutting conventions — do not skip):** if the app's GA4
event-wiring convention (`lib/policy.ts` / consent gate) fires interaction events for other
button actions (send-message, upload-cv, generate-pdp, submit-feedback, thumbs up/down), wire the
same convention for the new dashboard actions (approve/reject/create/log-progress) — check how
`components/PdpGenerator.tsx` or `components/CvUpload.tsx` do it and mirror it; do not invent a
new analytics mechanism.

## Acceptance criteria
- [ ] `lib/dashboard.ts` with typed client functions for: `getDashboardSummary`,
      `createGoal`/`updateGoal`/`deleteGoal`, `createMilestone`/`updateMilestone`/
      `deleteMilestone`, `createTask`/`updateTask`/`deleteTask`, `addProgress`/`listProgress`.
      Unit tests (mirror `lib/roles.test.ts`/`lib/profile.test.ts` if present, else the repo's
      existing `lib/*.test.ts` convention) with an injected fake `fetchImpl`.
- [ ] `/dashboard` route: guest → sign-in/upgrade prompt (no raw 403); logged-in user → the board.
- [ ] Approve/reject actually flips `status` / deletes a proposed row via the real endpoints
      (component test with a fake API client).
- [ ] % to target date and streak/progress numbers render from the summary endpoint.
- [ ] Nav link added from chat/roles/profile/pdp pages to `/dashboard` (and back).
- [ ] `npm run lint`, `npx tsc --noEmit`, `npm test` (the exact commands `frontend-ci.yml` runs)
      all green.

## Design references
- dev-board/app-design-and-features.md §5.2 "Dashboard — the living Personal Development Plan",
  §9 API surface table.
- dev-board/plan.md Phase 8.
- Patterns to mirror: `frontend/lib/roles.ts`, `frontend/app/roles/page.tsx`,
  `frontend/components/RoleRequirements.tsx`, `frontend/lib/profile.ts`,
  `frontend/components/ProfileView.tsx`, `frontend/components/UpgradePrompt.tsx` (guest
  sign-in-with-preserved-session affordance), `frontend/components/Chat.tsx` (nav header links).
- Backend contract: `backend/app/api/dashboard.py`, `backend/app/schemas/dashboard.py` (P8-02).

## Constraints / non-goals
- No backend changes in this task (P8-01..P8-04 already shipped the API).
- No charting library addition unless one is already a frontend dependency — keep the first cut
  lightweight (plain CSS/SVG), consistent with the rest of the frontend's dependency posture.
- No changes to the chat graph / native tools (P8-03) — this task only consumes the human CRUD
  endpoints (P8-02), never calls chat.
