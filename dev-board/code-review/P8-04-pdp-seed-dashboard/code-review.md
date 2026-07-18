# Code review — P8-04-pdp-seed-dashboard · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | app/services/pdp_seed.py:110 | `_clean_item` strips *all* `*` and `__`, so meaningful literals (`A* search`, `5* rating`) get mangled to `A search` / `5 rating`. Acceptable tradeoff for a deterministic parser, but lossy. | Optional: only strip `*`/`__` used as paired emphasis markers; leave as-is if the simplicity is preferred. |
| C2 | nit | app/services/pdp_seed.py:149 | Regeneration de-dup is read-then-write (`list_goals` → `create_goal`); two truly-concurrent PDP generations for the same goal could each see no match and create two goals. No locking required by the task, and seeding is fail-soft, so low risk. | None required; note the small window. |

## Notes
- Acceptance criteria all met and directly tested: one `source="ai"`/`proposed` goal + parsed
  milestones/tasks (`test_successful_generation_seeds_one_proposed_goal_with_rows`), regeneration
  reuses without duplicating and refreshes `target_date`
  (`test_regeneration_reuses_goal_without_duplicating`), seeding failure does not fail the PDF
  (`test_seeding_failure_does_not_fail_pdp_response`), and parser unit coverage
  (`tests/test_pdp_seed.py`: bullets, numbered, markdown/checkbox strip, prose-skip, dedup, cap,
  truncate, degrade-to-empty).
- Correctness: all `DashboardService` call sites match its signatures (kw-only `source`;
  `list_milestones` `| None` handled via `or []`; `update_goal(user_id, id, GoalUpdate)`).
  Seeding uses the raw `career_goal` — consistent with the persisted `pdps` row and PDF title, so
  the de-dup key aligns across regenerations.
- Attribution reuses P8-02 verbatim (`source="ai"` only; never sets `status`) — resolves to
  `proposed`, matching the design's propose→approve posture. No re-implementation of resolution.
- Fail-soft is correctly scoped: `_seed_dashboard` wraps the whole seed call in try/except +
  `logger.exception`, runs only after a successful `PdpGenerated`, and never blocks the PDF.
- Security: no untrusted-input sink here — titles are stored as data (no SSRF/injection/exec);
  `user_id` is a real account (guests rejected at router). Defensive `_MAX_ITEMS_PER_SECTION` cap
  prevents a pathological plan from flooding the dashboard.
- SoC respected: translation logic isolated in `pdp_seed.py`; `PdpService` just calls it; store
  wiring reused via `build_dashboard_service` (no duplication). Layering intact.
- Verified `uv run --no-sync pytest tests/test_pdp_seed.py tests/test_pdp_service.py -q` → 20 passed.
- Out-of-scope files in the working tree (dashboard_* from P8-01/02/03, CI config from
  FIX-11) were ignored per the dispatch note.
