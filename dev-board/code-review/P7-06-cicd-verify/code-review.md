# Code review — P7-06-cicd-verify · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | frontend-ci.yml:47 vs engineer.md How-to-verify | CI installs deps with `npm ci` (fails on lockfile drift); engineer verified against the pre-existing `node_modules` and did not run `npm ci`. Low risk — a lockfile-sync divergence would only surface in CI, not locally. | No change required; note only. Optionally run `npm ci` once to confirm `package-lock.json` is in sync. |

## Notes
Verification-only task (no product code). `git status`/`git diff` confirm **no source
changes** attributable to this task — the untracked/modified files in the tree are the
prior P7-01..P7-05 deliverables, and `engineer.md` correctly reports "Files changed: None".

I reproduced every CI gate against the current working tree using the **exact** commands
from `.github/workflows/backend-ci.yml` and `frontend-ci.yml`; all numbers match the
report exactly:

Backend (curated venv, `uv run --no-sync`):
- `ruff check .` → All checks passed
- `ruff format --check .` → 216 files already formatted
- `mypy app/ migrations/` → Success: no issues found in 130 source files
- `pytest` offline → 653 passed, 59 skipped (integration + OCR gated off)
- Live-DB pass (`pgvector/pgvector:pg16` up via dev-ports override → `alembic upgrade
  head` → `pytest`) → **711 passed, 1 skipped** — reconciles: the 58 DB-gated integration
  tests that skip offline execute live; the remaining 1 skip is the tesseract-binary OCR
  environmental skip, not a DB gate. Container torn down after.

Frontend (`frontend/`):
- `next lint` → No ESLint warnings or errors (deprecation notice only, non-blocking)
- `tsc --noEmit` → clean, exit 0
- `jest --watchAll=false` → 18 suites / 167 tests passed

Cross-checks: CI's curated install list (`backend-ci.yml`) and `backend/Makefile`'s
`install` target are in sync (identical dep list ending `... langgraph python-multipart`);
mypy scope `app/ migrations/` matches CI. Node caveat (local 18 vs CI 22) is documented
and benign — I reproduced green on the local Node and nothing depends on a Node-22-only
feature.

P7 CI/CD is fully green; no root-cause fix was required.
