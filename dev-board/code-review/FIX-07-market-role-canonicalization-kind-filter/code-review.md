# Code review — FIX-07-market-role-canonicalization-kind-filter · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | app/ingestion/taxonomy_seed.py (deploy note) | Taxonomy `KbDocument` rows seeded before this change carry no `meta["kind"]`; under the new filter `_resolve_baseline` will skip them and fall back to the user-stated role until the (idempotent) taxonomy seed is re-run. Not a code defect — deploy-ordering only. | On rollout, re-run the taxonomy seed so existing occupation docs get stamped. No code change required. |

## Notes
- Fix is correct, minimal, and localized as the task asked. `_resolve_baseline` now requests `k=BASELINE_SEARCH_K (5)` and returns the first hit whose **parent** `KbDocument.meta["kind"] == TAXONOMY_KIND`, else falls back — so a higher-ranked role-profile summary or learning resource in the same `curated` corpus can no longer hijack canonicalization. No SQL-level JSONB filter introduced; `hybrid_search` signature untouched.
- Non-taxonomy docs are skipped by `meta.get("kind") != TAXONOMY_KIND`, so they're excluded even if their own kind were absent — safe by construction. Non-dict/missing `meta` degrades to skip → fallback (no crash). Bounded `session.get` loop (k≤5) is not a perf concern.
- Single-source-of-truth constants verified: `grep '_KIND = "' app/` returns only `app/repositories/kb_kinds.py`; `market_agent` (imports + uses `ROLE_PROFILE_KIND` at role-profile summary write, `TAXONOMY_KIND` at filter), `taxonomy_seed`, and `learning_resources` (re-export, `__all__` preserved) all import from it. No leftover literal drift; `kind="occupation"` gone. Constant values match the prior literals (`role_profile`, `learning_resource`) so no behavior change for existing producers.
- Regression tests genuinely capture the bug: `test_resolve_baseline_matches_taxonomy_by_kind_not_top_rank` scripts a summary chunk (score 0.95) out-ranking the occupation (0.40) and asserts the occupation still wins — would have failed pre-fix (`k=1` took the summary). Public-wrapper and no-taxonomy-fallback cases also covered. The `test_p6_exit_verification.py` helper change (`kind="occupation"` → `TAXONOMY_KIND`) is a legitimate correctness fix aligning the test seed with production stamping, not a weakened assertion.
- Verified locally: `ruff check` on the 4 changed source files → clean; `pytest tests/test_market_agent.py tests/test_taxonomy_seed.py -k "baseline or canonical or kind or seed"` → 19 passed. Live-DB p6 suite not re-run here (no reachable Postgres in this env); engineer reports 10 passed against a migrated DB — plausible and consistent with the diff.
- Acceptance criteria met: regression proves pre-fix failure; constants defined once and imported everywhere; existing suites unchanged in behavior save the new `meta["kind"]` field + top-k filter.
