# Task FIX-11-backend-ci-reportlab-missing — backend-ci pytest collection fails: `reportlab` not curated into CI venv

- **Phase:** cross-cutting   **Status:** ENG   **Tags:** (I)

## Scope
The real `backend-ci.yml` run right after P7 landed (log saved at
`dev-board/failed_pipeline_after_p7.txt`) fails at the `pytest` step with **23 collection
errors**, all the same root cause:

```
tests/test_pdf_builder.py:10: in <module>
    from app.pdf import (
app/pdf/__init__.py:4: in <module>
    from app.pdf.builder import (
app/pdf/builder.py:26: in <module>
    from reportlab.lib.colors import HexColor
E   ModuleNotFoundError: No module named 'reportlab'
```

`ruff check`, `ruff format --check` and `mypy` all pass earlier in the same job (mypy's
`ignore_missing_imports` tolerates the untyped import), but `pytest` actually imports
`app.main` (and transitively `app/pdf/builder.py`, added by P7-02), so **every** test module
that imports `app.main` (or `app.api.pdp` / `app.services.pdp` directly) fails to collect —
21 API-level test files + `test_pdf_builder.py` + `test_pdp_service.py`.

**Root cause (same recurring class as FIX-01/02/03/04/09):** `backend/pyproject.toml`
already lists `reportlab>=4.0.0` as a real runtime dependency (P7-02), but backend CI does
**not** run a full `uv sync` — it installs a hand-curated, deliberately-light package list
(see the long comment block in `.github/workflows/backend-ci.yml` right above the "Install
dependencies" step, and the mirrored list in `backend/Makefile`'s `install` target) so CI
avoids pulling the heavy ML stack (torch/docling). P7-02 added a new **always-imported**
runtime dependency (`app/pdf/builder.py` is imported at module scope by `app/services/pdp.py`
→ `app/api/pdp.py` → `app/main.py`, so pytest hits it during collection for nearly every test
file) but nobody added `reportlab` to the curated list. `reportlab` is pure-Python, no
C-extension/CUDA weight — it belongs in the "light, must-curate" category alongside
`joserfc`/`authlib`/`langgraph`, not the excluded ML stack.

## Fix
1. Add `reportlab` to the `uv pip install ...` curated dependency line in
   `.github/workflows/backend-ci.yml` (the "Install dependencies" step).
2. Add it to the identical list in `backend/Makefile`'s `install` target (the workflow's own
   comment says "Keep this list in sync with the backend/Makefile `install` target" — this
   was violated for `reportlab`, don't repeat that for whatever comes next).
3. Extend the explanatory comment block above the CI step (matches the existing style — one
   sentence per added light dep, explaining who imports it and why it must be curated in) to
   cover `reportlab`.
4. Re-run the **exact** commands from `backend-ci.yml` locally (ruff check, ruff format
   --check, mypy, then `pytest` in a venv that mirrors the curated list — not a full `uv
   sync`) and confirm the 23 collection errors are gone and the full suite passes.
5. Grep for any other newly-added-but-uncurated runtime import while you're in there (quick
   sanity check only — do not go hunting broadly; this task is scoped to the reportlab gap
   the failed run surfaced).

## ⚠️ Concurrency notice
**Another engineer is actively implementing P8 (Dashboard) in this same working tree right
now.** Keep this fix **strictly scoped** to `.github/workflows/backend-ci.yml` and
`backend/Makefile` (+ maybe a one-line comment). Do **not** touch `app/pdf/`,
`app/services/pdp.py`, `app/api/pdp.py`, `app/main.py`, `app/bootstrap.py`,
`app/app_state.py`, or any dashboard-related files — P7's code is already correct and
reviewed; only the CI curation list is stale. If your local `pytest -q` run picks up
in-progress, uncommitted P8 changes and something *unrelated* to reportlab is red, do not fix
it — note it in your report and leave it for the P8 task's own pipeline.

## Acceptance criteria
- [ ] `reportlab` added to both the CI workflow's curated install line and
      `backend/Makefile`'s `install` target, with a comment explaining why (mirrors the
      existing per-dependency comment style).
- [ ] Local reproduction of the CI `pytest` step (curated-venv style, not full `uv sync`)
      passes — the 23 collection errors from `dev-board/failed_pipeline_after_p7.txt` are
      gone.
- [ ] `ruff check`, `ruff format --check`, `mypy` (CI's exact commands) still green.
- [ ] Report states plainly: root cause, the two files changed, and confirmation the fix is
      scoped exactly as described (no P7/P8 source files touched).

## Design references
- Precedent: `dev-board/code-review/FIX-01-backend-test-deps/`,
  `FIX-02-mypy-ci-curated-deps/`, `FIX-03-pytest-ci-missing-deps/`,
  `FIX-04-docling-bytes-import-guard/`, `FIX-09-taxonomy-fixture-gitignored/` — the same
  "curated CI venv missing a newly-added light dep" class of bug, same fix shape.
- `dev-board/failed_pipeline_after_p7.txt` — the actual failed run log.

## Constraints / non-goals
- No feature work. No changes to P7 or P8 application code. This task exists solely to make
  the CI curated dependency list match reality again.
