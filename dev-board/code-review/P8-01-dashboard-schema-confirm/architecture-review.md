# Architecture review — P8-01-dashboard-schema-confirm · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §5.2 attribution | Every mutable dashboard entity carries `source = user\|ai` (line 267, 714) | `source` + `ck_*_source` CHECK on goals/milestones/tasks/progress_entries | none |
| A2 | §5.2 proposed→approved | `proposed` state present so AI-proposal flow needs no later migration | `proposed` in all three lifecycle vocabularies (`_GOAL/_MILESTONE/_TASK_STATUS_VALUES`); progress_entries correctly stateless (append-only log) | none |
| A3 | §5.2 approval marker | Decide `approved_at`/`approved_by` now vs defer | DEFER — `status != 'proposed'` = approved, `updated_at` captures timestamp, `approved_by` redundant under strict user-scoping; additive if wanted later | none (YAGNI, cheap-to-unwind, matches P2-05 deferral) |
| A4 | §5.2 streak/trend + §4 store | Efficient `(user_id, created_at)` scan for streaks; Postgres only | Migration 0008 replaces single-col `user_id` idx with composite `(user_id, created_at)`; leading col still covers FK lookup so no redundant index | none |
| A5 | §8 structure / migration hygiene | New Alembic revision (never edit applied one); model+migration in sync | New rev `0008` (0007→0008), matching ORM `Index(...)`; autogen drift check empty | none |
| A6 | Non-goals | Schema only — no routes/tools/UI/repo | No repository/API/tool added; confirmed no dashboard repo exists (P8-02 scope) | none |

## Cross-cutting checks
- [x] Fits target structure (§8) `repositories/models/` + `migrations/`; layering untouched (no routes/tools)
- [x] Honors locked decisions — Postgres (pgvector+JSONB)+Redis only; checked-varchar not native ENUM (P2 posture)
- [x] Interfaces-before-implementations — N/A (schema-only); repository seam left for P8-02 as designed
- [x] Budget posture — no new infra/services; pure index refinement

## Notes
- The `approved_at`/`approved_by` = DEFER ruling is sound and design-consistent (§5.2 line 267/714: attribution via `source`, ownership enforced by user-scoping). P8-02/P8-03 build approve/reject as a `status` flip filtered on `source='ai' AND status='proposed'` — no schema dependency blocks them. Blessing this as the settled design; do not re-litigate an audit column unless a real audit-trail requirement surfaces.
- Dropping the redundant single-column `user_id` index (leading-column coverage) is standard and reduces write cost on the append-only log — no follow-up needed.
- Migration is a pure index change (no columns/constraints/data), correctly reversible in `downgrade()`.
