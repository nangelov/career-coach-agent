# Architecture review — FIX-11-backend-ci-reportlab-missing · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | CI curation posture (my logged FIX-01/09 ruling: curated light install must list every always-imported runtime lib) | `reportlab` added to the curated `uv pip install` line so pytest can import `app/pdf/builder.py` at collection | Added `reportlab` to the CI `uv pip install` line (`.github/workflows/backend-ci.yml`) | none |
| A2 | Makefile/CI parity (workflow comment mandates "keep in sync with backend/Makefile install target") | identical curated list in `backend/Makefile` `install` target | Added `reportlab` to the identical Makefile line; both lists now match verbatim | none |
| A3 | Dependency truth | new dep must be a real declared runtime dep, not invented in CI | `reportlab>=4.0.0` is declared in `backend/pyproject.toml:42` (P7-02); curation now matches reality | none |
| A4 | Budget/light-tier posture (§11; CI comment intent) | `reportlab` classified light (pure-Python, no torch/CUDA), heavy ML stack (torch/sentence-transformers/docling) stays excluded | Placed in light tier; comment extended (one sentence: who imports it + why light); full `uv sync` deliberately NOT adopted | none |
| A5 | Scope containment (concurrency notice — P8 in flight) | diff limited to `.github/workflows/backend-ci.yml` + `backend/Makefile`, no P7/P8 source | `git diff` confirms only those 2 files (7 insertions, 3 deletions); `app/pdf/`, `app/services/pdp.py`, `app/api/pdp.py`, `app/main.py`, `app/bootstrap.py`, dashboard files untouched | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — CI-config-only change, no application layers touched
- [x] Honors locked decisions — no ReAct parser / Postgres+Redis / SSO / in-process embeddings affected; ML stack still excluded from CI venv
- [x] Interfaces-before-implementations — N/A (no source change)
- [x] Budget posture respected — light pure-Python dep curated in; heavy ML stack stays out of the free-tier CI venv

## Notes
- Textbook instance of the recurring "curated CI venv missing a newly-added light runtime dep" class (FIX-01/02/03/04/09). Fix shape is identical and correct: curate the light dep rather than fall back to a full `uv sync`, keeping torch/sentence-transformers/docling out of CI.
- Comment block was extended in the workflow (matches the existing per-dep style). The Makefile carries no duplicate prose comment — it points at the workflow as the source of truth — so no divergence introduced.
- Design risk / recurring gap: this is now the sixth time an always-imported runtime dep slipped past the hand-curated list. The root cause is a manual sync between `pyproject.toml`, the workflow, and the Makefile with no guard. Out of scope for this hotfix, but worth a future follow-up (e.g. a `light` dependency extra installed by both CI and Makefile, or a check that fails when an always-imported top-level dep is absent from the curated line). Logged as a standing follow-up, not a blocker here.
- Engineer's sanity grep (anyio/httpx/redis/starlette all transitive; sentence-transformers/docling deliberately lazy) is consistent with the current import graph — no other curation gap surfaced.
