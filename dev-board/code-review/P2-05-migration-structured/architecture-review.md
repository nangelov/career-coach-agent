# Architecture review — P2-05-migration-structured · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure / models layout | New `repositories/models/<group>.py` module(s) + one import in `models/__init__.py`, within the blessed P2-03 subpackage convention | `models/jobs.py` (`Job`) + `models/dashboard.py` (`Pdp`/`Goal`/`Milestone`/`DashboardTask`/`ProgressEntry`), both registered in `__init__.py` + `__all__`; table-group comment updated | None — follows the blessed layout |
| A2 | §4 table set | `jobs`, `pdps`, `goals`, `milestones`, `tasks`, `progress_entries` | All 6 tables present with the listed columns | None |
| A3 | §4 store choice | jobs/pdps/dashboard = plain relational + JSONB, **no pgvector** | No `vector` columns; `raw`/`content` = JSONB; empty-autogenerate drift check confirms parity | None |
| A4 | §5.2 attribution | `tasks.source = user\|ai`, checked | `ck_tasks_source` CHECK over `String(8)`; `source` also on `goals`/`milestones`/`progress_entries` (documented superset) | None — superset is a reasonable, forward-compatible read of §5.2 |
| A5 | §5.2 AI-write safety (proposed → approve) | Schema must not preclude a future pending-approval state | `'proposed'` seeded in every `status` vocabulary (goals/milestones/tasks) so the P9-era workflow needs no migration; `approved_at` deferred as allowed | None |
| A6 | §4 GDPR cascade posture (matches P2-03/04) | user-delete cascades owned rows; goal→milestone→task cascade | `pdps/goals/progress_entries.user_id` CASCADE; `milestones.goal_id`, `tasks.goal_id` CASCADE; `tasks.milestone_id`, `progress_entries.goal_id/task_id` SET NULL | None — cascade shape is coherent and verified in `pg_constraint` |
| A7 | §4 jobs = shared cache | "normalized job listings … dedup, cache, match scores" | `jobs` has no `user_id` (global cache, untouched by user-delete); dedup key `UniqueConstraint(source, external_id)`; `source_url` nullable/non-unique; `raw JSONB` retained; `match_score` nullable global placeholder | None — per-user matching deferred to a future `user_job_matches` join table (blessed, see Notes) |
| A8 | §5.2 append-only log | `progress_entries` append-only, no update path | No `updated_at` column; no update path modeled | None |
| A9 | Migration chaining | `down_revision` chains onto P2-04 head; single head | `0004` → `0003`; chain `0001→0002→0003→0004` linear, single head | None |
| A10 | Checked-varchar-not-ENUM (P2-03 ruling) | `status`/`source` as `String`+`CheckConstraint`, not PG `ENUM` | All status/source columns are `String` + named `CheckConstraint` | None |
| A11 | Naming vs Celery `app/tasks/` | Dashboard `tasks` table must not be confused with Celery task modules | ORM class `DashboardTask` → table `tasks`; documented in docstring; no `app/tasks/` change | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — schema-only, lives entirely in the repository/migrations layer; no service/router/agent touched
- [x] Honors locked decisions — Postgres (pgvector+JSONB) + Redis only, no MongoDB; no ReAct parser / SSO / embeddings surface touched here
- [x] Interfaces-before-implementations — N/A (data layer); models sit on the shared `Base` the repository layer already queries through
- [x] Budget posture respected — self-hosted Postgres, no managed tier, no paid dependency

## Notes
- **Blessed design ruling (record for consistency):** `jobs` as a global, unscoped cache with the per-user
  match score deferred to a future `user_job_matches(user_id, job_id, score)` join table is the correct read
  of §4 ("dedup, cache, match scores"). A per-user score does not belong on a globally-shared row; the nullable
  global `match_score` placeholder is the task's explicitly-accepted simplification. Approved — future per-user
  matching should land as the documented join table (cascading `user_id`), not by adding `user_id` to `jobs`.
- **Dedup key `(source, external_id)` over `source_url`** is well-justified (URLs redirect / carry tracking
  params); crawled profiles get a synthetic `(source='crawl', external_id=<url-hash>)` at the ingestion layer.
  Approved as the natural key.
- **`source` on all four dashboard entities** (superset of the `tasks`-minimum the task required) and
  `'proposed'` seeded in every `status` vocabulary are forward-looking but design-aligned — they let the P9
  "proposed → user approves" workflow (§5.2, still-open decision #8/P9) land without a schema migration. No
  premature coupling to later phases: these are inert columns/values, no agent-write code exists yet.
- Follow-up (not blocking, later phase): when the dashboard-tools phase implements AI writes, confirm the
  `'proposed'` state is actually gated behind user approval per §5.2 before any `active`/`todo` transition.

## Verdict: APPROVED
