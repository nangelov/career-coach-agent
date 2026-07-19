# Code review — P10-07-cicd-verify · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| — | — | — | No defects. Verification-only task, no source changes. | — |

## Notes
Independently reproduced all 7 CI checks against the correct curated venv and a live,
migrated Postgres (docker `db`, `localhost:5432`). Every result matches `engineer.md`:

- **Curated-deps guard** (`python3 scripts/check_curated_deps.py`) → `Curated-dependency guard OK` (exit 0).
- **ruff check** → `All checks passed!`
- **ruff format --check** → `273 files already formatted`
- **mypy app/ migrations/** → `Success: no issues found in 160 source files`
- **pytest** (live migrated Postgres) → `1028 passed, 4 skipped` (4 skips are the OCR-toolchain tests, expected).
- **Frontend lint + tsc** → `✔ No ESLint warnings or errors`; tsc clean (exit 0).
- **Frontend jest** → `23 suites / 216 tests passed`.

Curated-venv fidelity confirmed (not a false green from the full dev venv):
`find_spec` shows `transformers=False`, `sentence_transformers=False`, `langgraph=True` in
`backend/.venv` — matching CI's curated install, per my recurring curated-venv-mypy check.

The only P10 dependency change is the new `transformers` runtime dep (P10-01 injection
classifier). It is correctly handled as a lazy, curated-**excluded** dep: import is deferred
to `app/guardrails/injection_classifier.py:170` (`from transformers import pipeline`, `# noqa
PLC0415`), and it is allowlisted in `scripts/check_curated_deps.py` INTENTIONAL_EXCLUSIONS
alongside `sentence-transformers` (same torch-heavy category). Guard passes; no ModuleNotFound
risk at CI collection since nothing imports it at module scope.

Local Node is v18.19.1 vs CI's Node 22; Next.js pinned to 15.x runs lint/tsc/jest identically —
acceptable, and the engineer disclosed it. Report is accurate and honest.
