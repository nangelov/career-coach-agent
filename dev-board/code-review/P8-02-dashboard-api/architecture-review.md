# Architecture review — P8-02-dashboard-api · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | schema in `schemas/`, port+double in `services/`, PG adapter in `repositories/`, thin router in `api/`, wired via `bootstrap.py` | `schemas/dashboard.py`, `services/dashboard.py` + `services/dashboard_store.py` (ABC+InMemory), `repositories/dashboard_store.py` (Postgres), `api/dashboard.py`, `build_dashboard_service` + `DASHBOARD_SERVICE` key + registered in `main.py` | none |
| A2 | Layering (Router→Service→Repo) | router HTTP-only; service depends on port; no DB/SQLAlchemy in router or service | router does auth/None→404 only; service depends solely on `DashboardStore`; SQLAlchemy confined to the repo adapter | none |
| A3 | Interface-before-impl | real seam so P8-03 tools reuse it | single `DashboardStore` ABC for the cohesive aggregate + `InMemory`/`Postgres` impls; snapshot bulk-read avoids N+1 | none — one-port-per-aggregate is a sound SoC call |
| A4 | AuthZ / user-scoping (§7, §5.2) | every write scoped to token subject; no path/body `user_id`; cross-user = uniform 404 | owner is always `current_user.user_id`; children reached only through an owned goal; miss→None→404, never distinguishing missing vs not-owned | none |
| A5 | Guest gate (§5.2 "dashboard requires an account") | guests 403 on every route | `_require_user` rejects `user_id is None` with 403 before any work | none |
| A6 | Attribution honesty (§5.2 `source=user\|ai`) | HTTP boundary writes `source="user"` only; no client-sent source; `source="ai"` reserved for P8-03 agent tools | `source` is response-only in schemas; service defaults `source="user"`; AI path is a service kwarg not reachable from the router | none |
| A7 | proposed→approve semantics (§5.2, P8-01 ruling) | user rows never start `proposed`; PATCH off `proposed`=approve; DELETE of `proposed`=reject; no separate approve endpoint | `*Update` status literals omit `proposed` (422 if sent); status flip is the approve path; DELETE is reject | none — matches blessed P8-01 ruling (status flip = approval) |
| A8 | API surface (§9) | `GET /api/dashboard` summary + CRUD `goals\|milestones\|tasks\|progress` | all present; milestones nested for create/list, flat `/milestones/{id}` for patch/delete (RESTful, task-sanctioned) | none |
| A9 | Summary first-cut (task §summary) | %-to-target via date-arithmetic (no new column), completion %, streak | `_time_progress_pct` (date math), `_task_completion_pct`, `_current_streak` (today/yesterday anchor); single scoped `snapshot` | none — no schema growth, matches P8-01 `approved_at` DEFER |
| A10 | Store posture (§4) | Postgres + Redis only; shared pool; DB cascades own hierarchy | shared `PostgresConnectionProvider`; `delete_goal` relies on CASCADE, `delete_milestone` on SET NULL; InMemory double mirrors both | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Repo)
- [x] Honors locked decisions (Postgres+Redis only; no new store; no ReAct/LLM coupling in a CRUD surface)
- [x] Interfaces-before-implementations (`DashboardStore` ABC + InMemory + Postgres)
- [x] Budget posture respected (no external calls, pure relational CRUD)

## Notes
- Phase fit: human-facing CRUD only; the `source="ai"`/`status="proposed"` path is a dormant service
  kwarg, so P8-03 reuses this service unchanged without prematurely wiring agent tools. Correct
  foundation-first sequencing; P8-04 (PDP-seeding) and P8-05 (UI) correctly deferred.
- Follow-up (non-blocking): no rate-limiting on dashboard CRUD — consistent with `GET/PUT /api/profile`
  and acceptable here (the guest gate + user-scoping bound the surface; §11 denial-of-wallet concerns
  target LLM/external calls, not plain relational CRUD). Revisit only if abuse surfaces.
