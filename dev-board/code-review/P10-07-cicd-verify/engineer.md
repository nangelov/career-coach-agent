# Engineer report — P10-07-cicd-verify · Revision 1

## Summary
Phase-exit CI/CD verification for P10. Ran the exact command sequence from
`.github/workflows/backend-ci.yml` and `.github/workflows/frontend-ci.yml` locally,
in the same working directories and with the same flags. **All 7 checks pass with
zero drift** — the P10-01..P10-06 work introduced no new curated dependency,
formatting, lint, type, or test regressions. No source fixes were required; this is
a clean confirmation pass.

## Files changed
- None. Verification-only task; nothing needed fixing.

## Key decisions
- Reproduced backend CI faithfully by starting the docker-compose `db`+`redis` (with
  dev-ports override), enabling pgvector (already present via the mounted init
  script), running `alembic upgrade head`, then `pytest` against the live migrated
  Postgres — so the ~40 integration modules **execute** rather than skip, matching
  CI's `postgres` service (design ref: backend-ci.yml service block, plan.md P10 exit).
- Used `uv run --no-sync` exactly as CI does, so the tools run in the curated venv
  rather than a full ML sync.
- Ran the stdlib-only curated-deps guard first (P8-08 precedent) before any install
  step, as CI orders it.

## How to verify
Backend (from `backend/`):
```
python3 scripts/check_curated_deps.py
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy app/ migrations/
# live DB (LIVE_DB_ENV): source ../.env, DATABASE_URL→localhost:5432
uv run --no-sync alembic upgrade head
uv run --no-sync pytest
```
Frontend (from `frontend/`): `npm ci && npm run lint && npm run type-check && npm test -- --watchAll=false`

## Tests (final step — mandatory)
All 7 CI checks, actual output:

1. **Curated-dependency drift guard** (`python3 scripts/check_curated_deps.py`)
   → `Curated-dependency guard OK: curated CI/Makefile lists cover every runtime dep.` (exit 0)

2. **Backend lint** (`uv run --no-sync ruff check .`)
   → `All checks passed!` (exit 0)

3. **Backend format** (`uv run --no-sync ruff format --check .`)
   → `273 files already formatted` (exit 0)

4. **Backend types** (`uv run --no-sync mypy app/ migrations/`)
   → `Success: no issues found in 160 source files` (exit 0)

5. **Backend tests** (`uv run --no-sync pytest`, live migrated Postgres)
   → `1028 passed, 4 skipped in 13.98s` (exit 0). The 4 skips are the OCR-toolchain
     tests that skip where `tesseract`/Ghostscript are absent (expected, same as CI).

6. **Frontend lint / type-check** (`npm run lint`, `npm run type-check`)
   → lint: `✔ No ESLint warnings or errors`; tsc: clean, no output (both exit 0).
     `npm ci` completed with lockfile in sync (exit 0; 2 pre-existing moderate audit
     advisories, unrelated to CI gates).

7. **Frontend tests** (`npm test -- --watchAll=false`)
   → `Test Suites: 23 passed, 23 total` / `Tests: 216 passed, 216 total` (exit 0).

No test failed; no root-cause fixes needed.

Environment note: local Node is v18.19.1 vs CI's Node 22, but Next.js is pinned to
15.x so lint/tsc/jest run identically; backend ran on the curated `.venv` via
`uv run --no-sync`, matching CI's curated install.

## Self-check
- [x] Meets acceptance criteria — all 7 checks pass using the exact CI commands; every new
      P10 dependency is already covered (no runtime dep introduced; `transformers` from S8
      is already allowlisted in `scripts/check_curated_deps.py` and the guard passes).
- [x] No secrets committed; verification-only, no layering impact.
- [x] Tests/lints pass (output pasted above).
