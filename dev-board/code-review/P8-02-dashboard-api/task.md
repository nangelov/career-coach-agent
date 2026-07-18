# Task P8-02-dashboard-api — `api/dashboard.py` CRUD + summary endpoint
- **Phase:** P8   **Status:** ENG   **Tags:** (B)
## Scope
tasks.md P8 items:
- "`api/dashboard.py` — CRUD goals/milestones/tasks, log progress, summary endpoint
  (`GET /api/dashboard`)."

Build the full dashboard CRUD surface on top of the `goals`/`milestones`/`tasks`/
`progress_entries` schema confirmed in P8-01 (`backend/app/repositories/models/dashboard.py`,
composite `progress_entries(user_id, created_at)` index already added).

Follow the existing Router → Service → Repository layering (see `app/api/pdp.py` +
`app/services/pdp_store.py` + `app/repositories/pdp_store.py` as the pattern to mirror: an
abstract port + in-memory test double in `app/services/`, a Postgres adapter in
`app/repositories/`, a thin router in `app/api/` that only does HTTP concerns and delegates to
a service).

**Endpoints (design §9 API surface table):**
- `GET /api/dashboard` — summary: goals with nested milestones + tasks, `%` progress to each
  goal's `target_date` (date-arithmetic, no new column), and a progress/streak summary derived
  from `progress_entries` (e.g. entries in the last N days / current streak — keep it simple,
  this is a first cut, not a full analytics engine).
- `GET/POST/PATCH/DELETE /api/dashboard/goals[/{id}]` — CRUD goals.
- `GET/POST/PATCH/DELETE /api/dashboard/goals/{goal_id}/milestones[/{id}]` — CRUD milestones
  under a goal (or a flatter `/api/dashboard/milestones/{id}` for update/delete — your call,
  keep it RESTful and consistent).
- `GET/POST/PATCH/DELETE /api/dashboard/tasks[/{id}]` — CRUD tasks (goal_id required,
  milestone_id optional, per the schema).
- `POST /api/dashboard/progress` — append a progress entry (optionally against a goal/task);
  `GET /api/dashboard/progress` — list/paginate entries for streak/trend rendering.

**Auth + attribution:**
- All endpoints require a logged-in user (`require_auth`; reject guests with `403` — dashboard
  is persistent, per §5.2 "Guests: dashboard requires an account"). Every write is scoped to
  `current_user.user_id` — no path/body `user_id` a caller could point at another user's data
  (mirror the AuthZ posture already used across `profile.py` / `pdp.py`).
- Every write through this **human-facing** CRUD API sets `source="user"` — do not expose a way
  for an HTTP caller to write `source="ai"` through these routes (that path is reserved for the
  native tools in P8-03, which run inside the agent graph, not through this router). This keeps
  the human/AI attribution honest at the boundary rather than trusting a client-sent field.
- Respect the `proposed` status semantics decided in P8-01: user-created rows never start in
  `proposed` (that status is reserved for AI-proposed rows created by P8-03's tools); a user
  `PATCH` that changes an AI-proposed row's `status` away from `proposed` is exactly the
  "approve" action (no separate approve endpoint needed — approving is just editing `status`).
  A user `DELETE` on a `proposed` row is exactly "reject".

## Acceptance criteria
- [ ] `app/schemas/dashboard.py` — request/response pydantic models for goals/milestones/tasks/
      progress entries + the `GET /api/dashboard` summary shape.
- [ ] `app/services/dashboard_store.py` (or similar) — abstract port(s) + in-memory test double,
      mirroring the `PdpStore` pattern; `app/repositories/dashboard_store.py` — Postgres adapter
      over the ORM models from P8-01.
- [ ] `app/services/dashboard.py` — the business-logic service (CRUD orchestration + summary
      aggregation), unit-testable against the in-memory store.
- [ ] `app/api/dashboard.py` — thin router wired via `app/bootstrap.py` (mirror
      `build_pdp_service`) and registered in `app/main.py`.
- [ ] Guests rejected (`403`) on every dashboard route; cross-user access denied (404/403, not
      leaking another user's row); every write from this router persists `source="user"`.
- [ ] Unit tests for the service (in-memory store) + router tests (fastapi TestClient, auth
      dependency overridden) covering CRUD, cross-user denial, guest denial, and the summary
      endpoint shape.

## Design references
- dev-board/app-design-and-features.md §5.2 "Dashboard — the living Personal Development Plan",
  §9 API surface table (`GET /api/dashboard`, `/api/dashboard/goals|tasks|progress`).
- dev-board/plan.md Phase 8.
- Pattern to mirror: `backend/app/api/pdp.py`, `backend/app/services/pdp_store.py`,
  `backend/app/repositories/pdp_store.py`, `backend/app/bootstrap.py` (`build_pdp_service`).
- Schema: `backend/app/repositories/models/dashboard.py` (as refined in P8-01).

## Constraints / non-goals
- No native tools yet (P8-03) — this task is the human-facing HTTP CRUD surface only, but design
  the service layer so P8-03's tools can reuse it (same service, different caller, writing
  `source="ai"` + `status="proposed"` instead of `source="user"`).
- No PDP-seeding logic here (P8-04).
- No frontend UI here (P8-05).
