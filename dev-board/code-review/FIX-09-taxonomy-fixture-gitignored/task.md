# Task FIX-09-taxonomy-fixture-gitignored — backend-ci fails: taxonomy_seed.json missing from git
- **Phase:** cross-cutting (CI/infra bugfix)   **Status:** ENG   **Tags:** (I)

## Scope
`dev-board/failed_pipeline.log` (a real `backend-ci` run, 2026-07-13) shows exactly one real test
failure — everything else in that log (`ERROR: duplicate key value...`, `ERROR: new row ... violates check
constraint...` in the Postgres container logs) is expected noise from tests that intentionally exercise
constraint violations; the summary line is `1 failed, 663 passed, 4 skipped`:

```
FAILED tests/test_taxonomy_seed.py::test_bundled_fixture_loads_and_is_valid - FileNotFoundError: [Errno 2]
No such file or directory:
'/home/runner/work/career-coach-agent/career-coach-agent/backend/app/ingestion/data/taxonomy_seed.json'
```

**Root cause (already diagnosed — verify it, don't re-derive from scratch):** the repo root `.gitignore` has
a bare `data/` pattern (line 14). Git gitignore patterns with no leading `/` match a directory of that name at
**any** depth, not just the repo root — so it unintentionally also matches
`backend/app/ingestion/data/` (P6-01's bundled ESCO/O*NET taxonomy fixture, added in
`dev-board/code-review/P6-01-taxonomy-seed/`) and silently excludes it from every commit. Confirm with:
```bash
git check-ignore -v backend/app/ingestion/data/taxonomy_seed.json
git ls-files backend/app/ingestion/data/     # currently empty — the files were never committed
```
The intent of the `data/` ignore rule is almost certainly the **root-level** `./data` runtime directory (an
empty local artifact dir, unrelated to the source tree), not any nested `data/` folder anywhere in the repo.

## Fix
1. Scope `.gitignore`'s `data/` entry to the root only (e.g. `/data/`) so it no longer shadows
   `backend/app/ingestion/data/` (or any other legitimate nested `data/` directory that might exist/be added
   later — check for others while you're in there, e.g. `frontend/**/data/` if any).
2. Commit `backend/app/ingestion/data/taxonomy_seed.json` and `backend/app/ingestion/data/README.md` (currently
   untracked due to the bug) to git.
3. Confirm no **other** files were silently excluded by the same broad pattern anywhere else in the tree
   (`git status --ignored` / a targeted `find . -type d -name data` cross-check against `git ls-files`) — fix
   any other casualties found, or explicitly note there were none.
4. Re-run the backend test suite from a **clean checkout perspective** — the bug only reproduces when the
   fixture is genuinely absent from the working tree the way CI sees it (a local dev checkout already has the
   untracked file on disk, which is why this wasn't caught locally). Verify by literally checking what `git
   ls-files` + a fresh `git stash -u` / temp-clone-style check would produce, or simplest: confirm
   `test_bundled_fixture_loads_and_is_valid` would fail if the file were untracked, and passes once it's
   `git add`ed and the ignore rule is fixed.

## Acceptance criteria
- [ ] `git check-ignore backend/app/ingestion/data/taxonomy_seed.json` exits non-zero (no longer ignored)
      after the `.gitignore` fix.
- [ ] `git ls-files backend/app/ingestion/data/` lists both `taxonomy_seed.json` and `README.md`.
- [ ] Full backend test suite green, including `tests/test_taxonomy_seed.py::test_bundled_fixture_loads_and_is_valid`.
- [ ] Report confirms whether any other files were casualties of the same over-broad `data/` pattern.

## Design references
- `dev-board/failed_pipeline.log` (the failing CI run)
- `dev-board/code-review/P6-01-taxonomy-seed/` (where the fixture was originally added — this bug means it
  was never actually merged into the tree that CI/anyone-else's clone sees)

## Constraints / non-goals
- No product code changes — this is a `.gitignore` + missing-commit fix only.
