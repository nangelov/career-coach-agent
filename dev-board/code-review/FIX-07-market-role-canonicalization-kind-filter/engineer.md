# Engineer report — FIX-07-market-role-canonicalization-kind-filter · Revision 1

## Summary
Fixed the P6-04 canonicalization gap flagged by P6-09: `_resolve_baseline` restricted its
taxonomy match to `source_type="curated"` and took the single top hybrid hit (`k=1`), so a
role-profile *summary* (or learning-resource) doc — which shares that `source_type` — could
out-rank and hijack the true taxonomy occupation, diverging from the persisted `canonical_role`
and perpetually missing the cached `role_profiles` row (202 loop).

Now the three shared-corpus `meta["kind"]` markers live in one module and `_resolve_baseline`
filters on `kind`, not rank.

## Files changed
- `app/repositories/kb_kinds.py` — **new.** Single source of truth for `TAXONOMY_KIND`,
  `ROLE_PROFILE_KIND`, `LEARNING_RESOURCE_KIND`. No heavy imports → no cycle between `ingestion/`
  and `agents/`.
- `app/agents/market_agent.py` — import `ROLE_PROFILE_KIND`/`TAXONOMY_KIND` from `kb_kinds`
  (removed the local `ROLE_PROFILE_KIND` literal); added `BASELINE_SEARCH_K=5`; `_resolve_baseline`
  now hybrid-searches top-k and returns the **first** hit whose parent `KbDocument.meta["kind"]
  == TAXONOMY_KIND`, else falls back to the user-stated role.
- `app/ingestion/taxonomy_seed.py` — import + stamp `meta["kind"] = TAXONOMY_KIND` on taxonomy
  `KbDocument` rows **and** their chunks (matches how the other two producers stamp both).
- `app/repositories/learning_resources.py` — `LEARNING_RESOURCE_KIND` is now imported from
  `kb_kinds` and re-exported (kept in `__all__`), so existing importers are unaffected and the
  literal is defined once.
- `tests/test_market_agent.py` — new regression tests (see below).
- `tests/test_taxonomy_seed.py` — assert the new `meta["kind"] == TAXONOMY_KIND` marker.
- `tests/test_p6_exit_verification.py` — **test bug fix:** `_seed_taxonomy_occupation` stamped an
  ad-hoc `kind="occupation"` that predates the shared constant; it now uses `TAXONOMY_KIND`.
  Without this the live tests would (correctly) skip the seed doc under the new filter and fall
  back to the user-stated role. Fixed the helper rather than weakening the assertions.

## Key decisions
- **Top-k + in-Python kind filter, not a new SQL JSONB parameter.** Kept the change minimal and
  localized (task point 3): `hybrid_search` gains no new filter arg; `_resolve_baseline` requests
  `k=5` and scans for the first taxonomy-kind parent. Cheaper than threading a JSONB predicate
  through `hybrid_search`/`hybrid_search_chunks` for a bounded k, and no repository signature
  churn (§8 layering untouched).
- **Single-source kind constants in `app/repositories/kb_kinds.py`.** Chosen over `ingestion/` or
  `agents/` because both of those depend on `repositories/` already (no import cycle), and the
  markers are fundamentally about KB-document classification. `TAXONOMY_KIND = "taxonomy_occupation"`
  (new; taxonomy docs previously carried no `kind` at all).
- Protects the §5.6 invariant: `role_profiles` is keyed once per canonical role and reused across
  users — read-time and mine-time canonicalization must agree.

## How to verify
```bash
# from backend/
uv run --no-sync ruff check app/ tests/
uv run --no-sync ruff format --check .
uv run --no-sync mypy app/ migrations/
uv run --no-sync pytest -q                       # offline (2 live-DB tests skip)
# live DB (DATABASE_URL built as the Makefile does → real migrated Postgres):
uv run --no-sync pytest -q tests/test_p6_exit_verification.py
```

## Tests (final step — mandatory)
- `ruff check app/ tests/` → All checks passed.
- `ruff format --check .` → 204 files already formatted.
- `mypy app/ migrations/` → Success: no issues found in 123 source files.
- `pytest -q` (offline) → **609 passed, 59 skipped** (+3 new market-agent regression tests; the
  2 live-DB p6 tests skip without a reachable DB).
- **Live DB** (real migrated Postgres @ localhost:5432): full suite **667 passed, 1 skipped**;
  `test_p6_exit_verification.py` alone **10 passed** — confirms the fix end-to-end and that the
  corrected `TAXONOMY_KIND` seed stamp resolves mine==read canonicalization.

New regression tests (in `tests/test_market_agent.py`):
- `test_resolve_baseline_matches_taxonomy_by_kind_not_top_rank` — a `ROLE_PROFILE_KIND` summary
  chunk out-ranks the taxonomy occupation (score 0.95 vs 0.40); asserts `_resolve_baseline` still
  returns the occupation's title/`taxonomy_id`/skills. **Would have failed pre-fix** (`k=1` took
  the summary → returned `"Market requirements: Data Scientist"`).
- `test_resolve_canonical_role_ignores_a_higher_ranked_summary` — the public wrapper agrees.
- `test_resolve_baseline_falls_back_when_no_taxonomy_in_top_k` — only a summary in top-k → falls
  back to the user-stated role (never adopts the summary's title).

No test weakened or deleted; the one test change (p6 seed helper) is a correctness fix, explained
above.

## Self-check
- [x] Meets acceptance criteria — regression proves pre-fix failure; kind constants defined once
  and imported everywhere (`grep '_KIND = "' app/` → only `kb_kinds.py`); existing P6 suites pass
  unchanged in behavior; full backend suite green incl. live-DB p6 tests.
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (constants in
  `repositories/`, no new driver access; `hybrid_search` signature unchanged).
- [x] Tests/lints pass (results pasted).
