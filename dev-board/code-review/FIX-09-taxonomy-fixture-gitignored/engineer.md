# Engineer report — FIX-09-taxonomy-fixture-gitignored · Revision 1

## Summary
CI `backend-ci` failed `test_bundled_fixture_loads_and_is_valid` with FileNotFoundError because the P6-01
taxonomy fixture was never actually in git. Root cause confirmed: the root `.gitignore` had a bare `data/`
pattern (line 14) which — being unanchored — matches a `data/` dir at **any** depth, silently excluding
`backend/app/ingestion/data/` from every commit. Local dev checkouts had the untracked file on disk, so the
bug only surfaced in CI's clean checkout. Fixed by anchoring the ignore to root (`/data/`) and tracking the
two fixture files.

## Files changed
- `.gitignore` — `data/` → `/data/`, so it only matches the root-level runtime dir, not nested `data/` dirs.
- `backend/app/ingestion/data/taxonomy_seed.json` — now tracked (was silently ignored).
- `backend/app/ingestion/data/README.md` — now tracked (was silently ignored).

## Key decisions
- Anchored the pattern to `/data/` (root only) rather than adding a negation `!backend/app/ingestion/data/`.
  The `data/` rule's intent is the root-level `./data` runtime artifact dir (verified: empty, untracked,
  unrelated to source). Anchoring is the minimal fix and also protects any future legitimate nested `data/`
  dir. No product code touched.

## Other casualties check
- `find . -type d -name data` yields exactly two: `./data` (root runtime dir, empty, intentionally ignored)
  and `./backend/app/ingestion/data` (the fixture). The fixture dir was the **only** casualty of the
  over-broad pattern.
- `git status --ignored` after the fix shows only standard caches/build artifacts
  (`.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `frontend/.next/`, `next-env.d.ts`,
  `tsconfig.tsbuildinfo`, `.claude/settings.local.json`) — all ignored by their own dedicated rules, none by
  the `data/` pattern.

## How to verify
```bash
git check-ignore backend/app/ingestion/data/taxonomy_seed.json   # exits non-zero (not ignored)
git ls-files backend/app/ingestion/data/                          # lists README.md + taxonomy_seed.json
git check-ignore data/                                            # root data/ still ignored (exit 0)
cd backend && .venv/bin/python -m pytest tests/test_taxonomy_seed.py -q
```

## Tests (final step — mandatory)
- `pytest tests/test_taxonomy_seed.py -q` → `16 passed` (target test green).
- Full backend suite `pytest -q` → `609 passed, 59 skipped`, **zero failures**. (Local skips more DB-only
  tests than CI's `663 passed, 4 skipped` because this host lacks the full live-DB set; the previously
  failing test now passes and nothing regressed.)
- `git ls-files` + `git check-ignore` confirm the fixtures are genuinely **tracked** (not just present on
  disk) and no longer ignored — i.e. a fresh CI clone will now contain them.

## Self-check
- [x] Meets acceptance criteria (check-ignore non-zero; ls-files lists both; suite green incl. target test;
      other-casualties confirmed = none but the fixture dir)
- [x] No secrets committed; no product/layering changes (gitignore + missing-file tracking only)
- [x] Tests pass (results pasted above)
