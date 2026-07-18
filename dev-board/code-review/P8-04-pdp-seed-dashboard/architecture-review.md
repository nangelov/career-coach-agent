# Architecture review — P8-04-pdp-seed-dashboard · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Seeding translation lives in `services/`, kept out of `PdpService` | New `app/services/pdp_seed.py` holds the prose→rows translation + de-dup rule; `PdpService` just calls it | None — clean SoC |
| A2 | Layering (Router→Service→Agent/Repo) | Services don't touch DB drivers; writes go through the P8-02 service seam | Seeding writes via injected `DashboardService`; no store/driver access; PDP router untouched | None — service→service composition is the intended reuse seam |
| A3 | Attribution reuse (§5.2, P8-02) | All seeded rows `source="ai"` → service resolves `proposed`; never set `status` here | `_AI_SOURCE="ai"` passed to `create_goal/milestone/task`; `status` never set in `pdp_seed.py` | None — matches [[ruling-dashboard-worker-write-path]] posture |
| A4 | Section→row mapping (task §"What to seed") | Only `learning_objectives`→milestones, `timeline_action_steps`→tasks; assessment/reference sections never seeded | Exactly those two `PdpContent` fields parsed; others ignored (confirmed against `schemas/pdp.py`) | None |
| A5 | No 2nd LLM pass (task constraint / budget §11) | Deterministic parser, no new deps | `parse_line_items` is pure regex/string; no ML, no LLM, no new deps | None — budget posture respected |
| A6 | De-dup / reuse (task §"Regeneration") | Simple, testable case-insensitive goal match; add only new rows | Exact casefold match on `title`/`target_role`, skips `abandoned`, refreshes `target_date`, per-title skip on rows | None — appropriately KISS, not fuzzy |
| A7 | Fail-soft (task §"Fail-soft") | Dashboard write failure never fails the PDF | `_seed_dashboard` swallows+logs any exception after PDF render/persist | None |
| A8 | Wiring / composition root | Reuse `build_dashboard_service`, no duplicated store wiring | `build_pdp_service` injects `build_dashboard_service(app)`; ctor arg required (PDP already requires Postgres) | None — same pattern as `build_chat_service` |
| A9 | Phase fit (P8) | No new endpoints/UI; belongs to P8 dashboard scope | No HTTP/schema/frontend changes; parses existing P7 prose sections | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — service-layer translation, DB access only via the P8-02 service
- [x] Honors locked decisions (Postgres+Redis only; no new stores; no ReAct; SSO-only path — guests 403'd at router before `generate`)
- [x] Interfaces-before-implementations — reuses the `DashboardService` seam verbatim for attribution; no re-implemented resolution logic
- [x] Budget posture respected — deterministic regex parser, zero new dependencies

## Notes
- Guest handling differs (correctly) from [[ruling-dashboard-worker-write-path]]: P8-03's chat node needed a guest fail-soft branch, but PDP is an auth-only path (router 403 before `generate`), so `user_id` is always a real account and a required (non-optional) `dashboard` ctor arg is right.
- `_MAX_ITEMS_PER_SECTION=25` is a reasonable defensive bound (YAGNI-safe: truncates, never rejects). No design concern.
- Accepted pattern for P9 write paths: service→service composition where one service reuses another's attribution resolution rather than re-deriving `source`/`status`. Consistent with the P8-02/P8-03 lineage; do not re-litigate.
