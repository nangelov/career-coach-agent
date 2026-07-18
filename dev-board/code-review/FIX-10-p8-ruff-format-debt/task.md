# Task FIX-10-p8-ruff-format-debt — Reformat P8-01/P8-02 files flagged by `ruff format --check`
- **Phase:** cross-cutting   **Status:** ENG   **Tags:** (B)
## Scope
The P8-03 code review (`dev-board/code-review/P8-03-dashboard-tools/code-review.md`, revision 1
notes) confirmed `ruff format --check .` currently reports **7 files "would reformat"** —
pre-existing debt from the already-DONE P8-01/P8-02 tasks (none touched by P8-03's diff, which
is itself format-clean):
- `app/repositories/dashboard_store.py`
- `app/services/dashboard.py`
- `app/services/dashboard_store.py`
- `migrations/versions/20260718_0008_progress_streak_index.py`
- `tests/test_dashboard_api.py`
- `tests/test_dashboard_service.py`
- `tests/test_dashboard_store_postgres.py`

This mirrors the earlier `FIX-06-ruff-format-check` task: the backend CI runs
`ruff format --check` (see `.github/workflows/backend-ci.yml`) and it is currently red on these
files, which will surface as a failure in the P8-07 CI/CD verification if left unfixed. Fix it
now, before more P8 tasks build on top of these files.

## Acceptance criteria
- [ ] `cd backend && ruff format .` (or targeted at the 7 files above) applied — formatting only,
      no behavior change.
- [ ] `ruff format --check .` is green repo-wide afterwards.
- [ ] `ruff check .` and `mypy` still clean; full test suite still green (no behavior changed by
      a pure reformat, but re-run to confirm).
- [ ] Confirm no other files outside this list also need reformatting (re-run the check first).

## Design references
- `.github/workflows/backend-ci.yml` (the `ruff format --check` gate this fixes).
- Precedent: `dev-board/code-review/FIX-06-ruff-format-check/`.

## Constraints / non-goals
- Formatting-only change. Do not alter logic, tests' assertions, or migration DDL semantics.
