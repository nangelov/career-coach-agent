# Engineer report — P8-01-dashboard-schema-confirm · Revision 1

## Summary
Audit/confirmation pass on the P2-05 dashboard schema (`goals`/`milestones`/`tasks`/
`progress_entries`) ahead of the P8 CRUD/summary API. The hierarchy, attribution, and cascade
posture already satisfy §4/§5.2 and were left untouched. **One** targeted refinement was
made: a composite `(user_id, created_at)` index on `progress_entries` for the streak/trend
queries `GET /api/dashboard` (P8-02) will run, replacing the now-redundant single-column
`user_id` index. New Alembic revision `0008` + matching ORM change, applied and verified
against the live Postgres container (no autogenerate drift afterwards).

## What already exists vs. what changed

**Confirmed sufficient — no change (points 1, 3-partial, 4):**
- **Attribution + `proposed` status (point 1):** every mutable entity (`goals`,
  `milestones`, `tasks`, `progress_entries`) carries a checked `source IN ('user','ai')`.
  `goals`/`milestones`/`tasks` `status` vocabularies each include `'proposed'`.
  `progress_entries` is append-only and has no lifecycle `status` (correct — it is a log,
  not a stateful entity). Still holds against the live models + migration `0004`.
- **Nesting + "% to target date" (point 3):** goals→milestones→tasks fan-out is already
  covered by `ix_goals_user_id`, `ix_milestones_goal_id`, `ix_tasks_goal_id`,
  `ix_tasks_milestone_id`. "% to target date" is a pure date arithmetic on already-indexed
  rows — no extra column/index needed.
- **Repository layer (point 4):** confirmed `app/repositories/` has **no** dashboard
  repository yet. Schema fully supports one; building it stays in P8-02 scope (not touched
  here).

**Refined — migration `0008` (point 3, streak aggregation):**
- `progress_entries` previously had only a single-column `ix_progress_entries_user_id`.
  Streak/trend views (§5.2) filter by `user_id` and order/group by `created_at`, which that
  index cannot serve without an extra sort. Added composite
  `ix_progress_entries_user_id_created_at (user_id, created_at)` and dropped the single-column
  index — because `user_id` leads the composite, it also covers the plain per-user FK lookup,
  so keeping both would be a redundant index paying write cost on every append. Pure index
  change; no columns/constraints/data touched.

## Key decisions

- **`approved_at` / `approved_by` — DEFER (point 2).** `status != 'proposed'` is sufficient
  to mean "approved/live": user-created rows never start in `proposed`; an AI-proposed row
  starts `proposed` and transitions to `active`/`todo`/etc. on approval, so the status column
  alone distinguishes pending from approved. Originator attribution is already carried by
  `source = ai`; the approval *timestamp* is captured by the existing `updated_at`
  (`onupdate=now()`). `approved_by` is redundant in a strictly user-scoped model — only the
  authenticated owner can approve their own rows (§5.2 "all AI writes are scoped to the
  authenticated user"). Adding either column now is YAGNI; the existing columns fully support
  the P8-02/P8-03 approve/reject flow (flip `status` from `proposed`, filter proposals by
  `source='ai' AND status='proposed'`). If explicit audit markers are wanted later they are a
  cheap additive, feature-scoped migration — consistent with the P2-05 docstring's deferral.
- **Drop the redundant single-column index rather than keep both** — standard Postgres
  practice (leading-column coverage) and avoids double write cost on the append-only log.

## How to verify
```
cd backend
docker compose -f ../docker-compose.yml -f ../docker-compose.dev-ports.yml up -d --wait db
make migrate-integration          # applies 0008
# inspect: \d progress_entries  → ix_progress_entries_user_id_created_at (user_id, created_at)
#          single-column ix_progress_entries_user_id is gone
make revision m="drift"           # autogenerate → empty upgrade() = no model/DB drift
```

## Tests (final step — mandatory)
- Live DB brought up (compose `--wait db`), `make migrate-integration` → `0007 -> 0008` applied.
- `\d progress_entries` confirms `ix_progress_entries_user_id_created_at (user_id, created_at)`
  present and the old `ix_progress_entries_user_id` removed.
- Autogenerate drift check: `alembic revision --autogenerate` produced an **empty** `upgrade()`
  (`pass`) → model and DB fully in sync. Throwaway file deleted.
- Scoped: `pytest tests/test_structured_models.py tests/test_p2_exit_verification.py -q` →
  **13 passed**.
- Full suite (live DB): `pytest -q` → **711 passed, 1 skipped** (skip is env-gated, unrelated).
- `ruff check` + `mypy` on the two changed files → clean.

## Self-check
- [x] Meets acceptance criteria: confirmation documented; one refinement made via new revision
      `0008` (never edited an applied migration) + matching ORM change, applied and verified;
      `approved_at`/`approved_by` decision documented with rationale.
- [x] No secrets committed; schema-only change respects Router→Service→Agent/Repo layering
      (no routes/tools/UI added — non-goals honored).
- [x] Tests/lints pass (pasted above).
