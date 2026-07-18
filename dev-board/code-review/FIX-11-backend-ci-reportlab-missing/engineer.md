# Engineer report — FIX-11-backend-ci-reportlab-missing · Revision 1

## Summary
Backend CI's `pytest` step failed after P7 landed with 23 collection errors, all
`ModuleNotFoundError: No module named 'reportlab'`. Root cause is the recurring "curated CI venv
missing a newly-added light runtime dep" class (same as FIX-01/02/03/04/09): backend CI deliberately
installs a hand-curated, light package list (not a full `uv sync`, to avoid the heavy ML/CUDA stack).
P7-02 added `reportlab>=4.0.0` as a real runtime dep and imports `app/pdf/builder.py` at module scope
(`app/services/pdp.py` → `app/api/pdp.py` → `app.main`), so pytest hits it during collection for nearly
every test file — but `reportlab` was never added to the curated list. `reportlab` is pure-Python
(no C-extension/CUDA weight), so it belongs in the "light, must-curate" category, not the excluded ML stack.

Fix: added `reportlab` to the curated `uv pip install` line in the CI workflow and the mirrored line in
`backend/Makefile`'s `install` target, and extended the CI comment block explaining who imports it and why.

## Files changed
- `.github/workflows/backend-ci.yml` — added `reportlab` to the "Install dependencies" curated
  `uv pip install` line; extended the per-dependency comment block to cover it (who imports it / why light).
- `backend/Makefile` — added `reportlab` to the identical `install`-target curated list (kept in sync,
  as the workflow comment requires).

No P7/P8 application source touched. `app/pdf/`, `app/services/pdp.py`, `app/api/pdp.py`, `app/main.py`,
`app/bootstrap.py`, `app/app_state.py`, and all dashboard files were left untouched.

## Key decisions
- Placed `reportlab` in the curated list rather than switching CI to a full `uv sync` — preserves the
  intentional exclusion of the heavy ML stack (torch/sentence-transformers/docling) per the existing CI
  design; `reportlab` is pure-Python so it fits the light tier alongside joserfc/authlib/langgraph.
- Kept both lists (workflow + Makefile) identical, as the workflow comment mandates.
- Sanity grep for other newly-added-but-uncurated runtime imports: enumerated all top-level modules
  imported under `app/`. The only third-party imports outside the curated list are `anyio`, `httpx`,
  `redis`, `starlette` — all transitive deps already pulled in by fastapi/openai/celery[redis], so no
  additional curation needed. `sentence-transformers`/`docling` remain deliberately lazy-imported and
  excluded. `reportlab` was the only gap.

## How to verify
From `backend/`, mirror the exact CI steps in the curated venv (not a full `uv sync`):
```
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy app/ migrations/
uv run --no-sync pytest
```
(To recreate the curated venv from scratch: `make install`, which now installs `reportlab`.)

## Tests (final step — mandatory)
- `uv run --no-sync ruff check .` → `All checks passed!`
- `uv run --no-sync ruff format --check .` → `231 files already formatted`
- `uv run --no-sync mypy app/ migrations/` → `Success: no issues found in 139 source files`
- `uv run --no-sync pytest -q` → `719 passed, 62 skipped in 11.83s`
  - **Zero collection errors** — the 23 `reportlab` collection errors from
    `dev-board/failed_pipeline_after_p7.txt` are gone.
  - The 62 skips are the live-DB integration suites, which skip without a reachable Postgres (identical to
    `make test`); in CI they execute against the Postgres service container.
- No test failures observed. No unrelated/in-progress P8 failures surfaced in this run.

## Self-check
- [x] Meets acceptance criteria (reportlab added to both curated lists + comment; 23 collection errors gone;
      ruff/format/mypy still green; scoped to the two CI files only)
- [x] No secrets committed; no application layering touched (CI-config-only change)
- [x] Tests/lints pass (output pasted above)
- [x] Strictly scoped: only `.github/workflows/backend-ci.yml` and `backend/Makefile` changed — no
      P7/P8 source files modified
