# Engineer report — P8-02-dashboard-api · Revision 1

## Summary
Built the full human-facing dashboard CRUD + summary surface (`/api/dashboard`) on top of the
P8-01 `goals`/`milestones`/`tasks`/`progress_entries` schema, following the established
Router → Service → Repository layering (mirrors the PDP/profile ports). The service layer is
designed so P8-03's native tools reuse it unchanged (`source="ai"` → `status="proposed"`), while
this HTTP router is honest at the boundary: every write is scoped to the token subject and stamped
`source="user"`, guests are `403`, and cross-user access is a uniform `404`.

## Files changed
- `app/schemas/dashboard.py` — new. Request/response models for goals/milestones/tasks/progress +
  the `GET /api/dashboard` summary shape. `*Update` status literals exclude `proposed` (reserved
  for AI writes) so a human PATCH cannot set it; `source` is response-only (never client-sent).
- `app/services/dashboard_store.py` — new. `DashboardStore` ABC (one port for the cohesive
  aggregate) + `InMemoryDashboardStore` test double (enforces the same user-scoping, cascade, and
  milestone-detach rules as the DB) + a `DashboardSnapshot` bulk-read for the summary.
- `app/repositories/dashboard_store.py` — new. `PostgresDashboardStore` over the shared pool;
  user-scoped queries (goals by `user_id`, milestones/tasks via join to the owning goal), DB-level
  `CASCADE`/`SET NULL` own the hierarchy on delete, server-default timestamps read back via refresh.
- `app/services/dashboard.py` — new. `DashboardService`: attribution resolution (user vs
  AI-proposed), PATCH-as-approve semantics, and summary aggregation (time %, task completion %,
  streak). Pure date helpers unit-tested directly.
- `app/api/dashboard.py` — new. Thin router; `require_auth` + guest-`403` gate (`_require_user`),
  `None`→`404` mapping, no path/body `user_id`.
- `app/bootstrap.py` — added `build_dashboard_service` (mirrors `build_pdp_service`).
- `app/app_state.py` — added `DASHBOARD_SERVICE` key.
- `app/main.py` — registered `dashboard_router`.
- `tests/test_dashboard_service.py`, `tests/test_dashboard_api.py`,
  `tests/test_dashboard_store_postgres.py` — new.

## Key decisions
- **One store port for the whole aggregate** (not four narrow ones). The living PDP is one cohesive
  `goal → milestone → task` + progress aggregate (design §5.2); a single `DashboardStore` keeps the
  scoping/ownership rules in one place. Follows the interface-before-implementation idiom.
- **Attribution policy lives in the service, persisted verbatim by the store.** The service resolves
  `source`/`status` per caller — router → `source="user"` + normal starting status; P8-03 tools →
  `source="ai"` + `status="proposed"`. This is exactly the reuse the task asked for without leaking
  AI-write capability through the HTTP boundary (task §"Auth + attribution").
- **Approve/reject are edits, not new endpoints** (task §"proposed status semantics"): a PATCH that
  moves a `proposed` row to a normal status is "approve"; a DELETE of a `proposed` row is "reject".
  The human `*Update` schemas' status literals omit `proposed`, so a client can't write it (→ `422`).
- **Cross-user access = `404`, never leaked.** Every store method is user-scoped; a miss returns
  `None`/`False`, mapped to a uniform `404` (mirrors profile/pdp AuthZ posture, §7).
- **Summary is a first cut** (task explicitly): elapsed-time % via date-arithmetic (no new column),
  task-completion %, and a simple streak (consecutive days ending today/yesterday) over the
  append-only log. Loaded via a single bulk `snapshot` (4 scoped queries, no N+1).
- **DB cascades own deletes**: `delete_goal` is one `DELETE` relying on `ondelete=CASCADE`;
  `delete_milestone` relies on `ondelete=SET NULL` to detach (not delete) its tasks.

## How to verify
```
cd backend
# service + router (no DB needed)
.venv/bin/python -m pytest tests/test_dashboard_service.py tests/test_dashboard_api.py -q
# Postgres adapter against the live stack
set -a && . ../.env && set +a && \
  export DATABASE_URL="postgresql+asyncpg://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:5432/$POSTGRES_DB" && \
  .venv/bin/python -m pytest tests/test_dashboard_store_postgres.py -q
.venv/bin/ruff check app/…/dashboard*.py ; .venv/bin/mypy app/…/dashboard*.py
```

## Tests (final step — mandatory)
- `ruff check` (all 8 new/changed files) → All checks passed.
- `mypy` (schemas/service/store/repo/api + bootstrap/main/app_state) → Success, no issues.
  - One fix: `AsyncSession.execute(delete(...))` is typed `Result` (no `rowcount`); cast to
    `CursorResult[Any]` for the scoped-delete → bool. Recorded in agent memory.
- Full backend suite (live DB wired): **748 passed, 1 skipped** in ~17s (the skip is a pre-existing
  unrelated case). Dashboard tests: 34 service+api pass; 3 Postgres integration pass (round-trip,
  cross-user scoping, cascade+detach).

## Self-check
- [x] Meets acceptance criteria (schemas, store port + in-memory + Postgres adapter, service,
      thin router wired via bootstrap + registered in main; guest `403`, cross-user `404`,
      `source="user"` on every write; unit + router + Postgres tests).
- [x] No secrets committed; Router→Service→Repository layering respected (router has no DB imports;
      service depends only on the port; interface-before-implementation).
- [x] Tests/lints/types pass (pasted above).

## Notes / non-goals honored
- No native tools (P8-03), no PDP-seeding (P8-04), no frontend (P8-05). The service is the shared
  seam P8-03 will reuse. No rate-limiting on dashboard CRUD (consistent with `GET/PUT /api/profile`;
  the task's endpoint/acceptance list does not call for it).
