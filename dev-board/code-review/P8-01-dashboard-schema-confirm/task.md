# Task P8-01-dashboard-schema-confirm — Confirm dashboard tables from P2 + any refinements
- **Phase:** P8   **Status:** ENG   **Tags:** (B)
## Scope
tasks.md P8 item: "Confirm `goals`/`milestones`/`tasks`/`progress_entries` tables (from P2) + any refinements."

`goals`, `milestones`, `tasks`, `progress_entries` were already created in migration
`backend/migrations/versions/20260705_0004_structured_records.py` and ORM models
`backend/app/repositories/models/dashboard.py` as part of P2-05-migration-structured. This
task is an audit/confirmation pass ahead of building the P8 CRUD API and native tools on top
of them — verify the existing schema is sufficient, and make any small refinements needed
(migration + model, in sync) before the API task starts.

Specifically confirm/refine:
1. Every mutable entity (`goals`, `milestones`, `tasks`, `progress_entries`) has a `source`
   (`user`|`ai`) column and a `status` vocabulary that includes `proposed` where relevant
   (§5.2: AI writes are "proposed → user approves", never silent). Already true per the P2-05
   docstring — verify it still holds against the live models/migration.
2. Whether the "proposed → approved" workflow needs an explicit `approved_at` / `approved_by`
   marker, or whether `status != 'proposed'` is sufficient to mean "approved" (the P2-05
   docstring explicitly deferred this as a "later feature-scoped migration if wanted" — decide
   now, since P8-02/P8-03 build the approve/reject flow on top of this).
3. `GET /api/dashboard` (P8-02) needs a summary shape: goals with nested milestones/tasks, plus
   "% to target date" progress and streak/progress-entry aggregation. Check whether any
   indexes/columns are missing to compute that efficiently (e.g. an index on
   `progress_entries(user_id, created_at)` for streak queries) — add via a new Alembic revision
   if so.
4. Repository layer: check whether `app/repositories/` already has a dashboard repository (it
   does not, per a repo grep) — confirm P8-02 will need to add one; do not build the repository
   here (that's P8-02 scope), just confirm the schema supports it.

## Acceptance criteria
- [ ] Written confirmation (in `engineer.md`) of what already exists vs. what changed.
- [ ] If any refinement is needed: new Alembic revision (never edit an already-applied
      migration in place) + matching ORM model change, applied and verified against the local
      Postgres container.
- [ ] If no refinement is needed: say so explicitly and do not touch the schema — this task can
      be a no-op confirmation with no diff.
- [ ] Decision on `approved_at`/`approved_by` (add now or defer) is documented with rationale,
      since P8-02/P8-03 depend on it.

## Design references
- dev-board/app-design-and-features.md §4 "Dashboard (living PDP)", §5.2 "Dashboard — the
  living Personal Development Plan".
- dev-board/plan.md Phase 8 (lines ~155-163).
- `backend/app/repositories/models/dashboard.py`, `backend/migrations/versions/20260705_0004_structured_records.py`.

## Constraints / non-goals
- No API routes, no tools, no UI — schema/model confirmation only.
- Keep the change minimal; do not redesign the hierarchy.
