# Task P8-08-curated-deps-guard — Guard against curated-CI-dependency drift
- **Phase:** P8   **Status:** ENG   **Tags:** (I)
## Scope
tasks.md P8 item: "**Guard against curated-CI-dependency drift** — backend CI deliberately runs
a hand-curated `uv pip install <light-deps>` list (not a full `uv sync`) to avoid pulling the
heavy ML stack (torch/docling), mirrored in `backend/Makefile`'s `install` target. This exact
class of bug ("a new always-imported runtime dep lands in `pyproject.toml` but nobody adds it to
the curated list") has broken the real pipeline **six times** across P1–P7 (FIX-01, FIX-02,
FIX-03, FIX-04, FIX-09, FIX-11 — most recently `reportlab`, P7-02). Add an automated guard so it
can't recur silently: a small script/test (e.g. `scripts/check_curated_deps.py` or a `pytest`
case) that statically walks `app/`'s imports (or diffs `pyproject.toml`'s light/runtime deps
against the curated list, excluding an explicit ML-stack allowlist) and fails with a clear
message naming the missing package — wired as an early step in `backend-ci.yml` (and/or a
pre-commit/`make lint` check) so a future PR that adds a new light dependency fails fast locally
instead of only surfacing in a real `pytest` collection error on `main`/`version-2` after merge."

Read all six precedent FIX tasks first (`dev-board/code-review/FIX-01-backend-test-deps/`,
`FIX-02-mypy-ci-curated-deps/`, `FIX-03-pytest-ci-missing-deps/`,
`FIX-04-docling-bytes-import-guard/`, `FIX-09-taxonomy-fixture-gitignored/`,
`FIX-11-backend-ci-reportlab-missing/`) to understand the exact recurring failure mode before
designing the guard — they are all "curated CI venv missing a newly-added light dep", but not
identical (FIX-04/FIX-09 were adjacent variants: a real-import guard and a `.gitignore` fixture
exclusion, not literally a missing pip package). Scope the guard at the actual recurring core:
**a package `app/` imports at runtime that is declared in `backend/pyproject.toml` but absent
from both the CI workflow's curated install line and `backend/Makefile`'s `install` target.**

## Design (your call, but must satisfy all of the below)
1. **Detection approach.** Prefer statically parsing `backend/pyproject.toml`'s dependency list
   and diffing it against the curated install list(s) (`.github/workflows/backend-ci.yml` +
   `backend/Makefile`), rather than walking every `import` in `app/` (which would false-positive
   on stdlib/already-curated/dev-only imports and is a much bigger surface). An explicit,
   documented **ML-stack allowlist** (torch, docling, sentence-transformers, and whatever else is
   intentionally excluded from the curated CI venv today — check both files for the current
   exclusions) is the difference set the check must respect: "in `pyproject.toml`, not in the
   curated list, not on the ML allowlist" ⇒ fail with the package name.
2. **Two curated lists, one source of truth.** `backend-ci.yml`'s comment already says "Keep this
   list in sync with the backend/Makefile install target" — today that's enforced by nothing.
   Consider whether the guard should also assert the workflow's list and the Makefile's list are
   identical to each other (not just each individually complete), since a drift *between* them is
   the same bug class in miniature.
3. **Wiring.** Runs as an early step in `backend-ci.yml` (before the expensive install/pytest
   steps, so it fails fast) — a `python scripts/check_curated_deps.py` step or a `pytest` case run
   with `make lint`/`make check`. Prefer a standalone script if it needs to run *before*
   dependencies are installed (parsing `pyproject.toml` needs no third-party deps); a `pytest`
   case is fine if it can run inside the curated venv itself.
4. **Fail message must name the exact missing package(s)**, not a generic "drift detected" — the
   whole point is a future PR gets a precise, actionable CI failure instead of a cryptic
   `ModuleNotFoundError` deep in `pytest` collection.

## Acceptance criteria
- [ ] A new check exists (script and/or test) that fails with a clear, package-named message when
      `pyproject.toml` declares a non-allowlisted runtime dep missing from either curated list.
- [ ] The check currently passes (today's curated lists are complete — no real drift right now,
      per P8-07's green run) — prove it by also testing the negative case: temporarily/in a unit
      test, simulate an uncurated dep and confirm the check fails with a useful message, then
      confirm it's clean again against the real files.
- [ ] Wired into `.github/workflows/backend-ci.yml` as an early step (before dependency install /
      pytest), so it would have caught FIX-01/02/03/04/09/11's root cause before merge.
- [ ] `README`/comment in the check itself (or right above the CI step) explains what it does and
      why, so the next person adding a light dependency knows this exists.
- [ ] Full backend + frontend CI command sets still green after adding this step (this task must
      not itself break CI).

## Design references
- `.github/workflows/backend-ci.yml` (the curated install step + its "keep in sync" comment),
  `backend/Makefile` (`install` target).
- Precedent (read all six): `dev-board/code-review/FIX-01-backend-test-deps/`,
  `FIX-02-mypy-ci-curated-deps/`, `FIX-03-pytest-ci-missing-deps/`,
  `FIX-04-docling-bytes-import-guard/`, `FIX-09-taxonomy-fixture-gitignored/`,
  `FIX-11-backend-ci-reportlab-missing/`.

## Constraints / non-goals
- Not a general dependency-management overhaul — do not switch CI to a full `uv sync` (that
  defeats the deliberate ML-stack exclusion this curated-list design exists for); this task adds
  a guard *around* the existing curated-list design, it doesn't replace it.
- No unrelated CI changes.
