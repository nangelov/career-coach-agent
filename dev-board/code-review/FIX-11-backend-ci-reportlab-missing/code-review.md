# Code review — FIX-11-backend-ci-reportlab-missing · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| — | — | — | No blocker/major/minor/nit found | — |

## Notes
- **Scope confirmed clean.** `git diff HEAD` touches exactly two files: `.github/workflows/backend-ci.yml`
  and `backend/Makefile` (8 / 2 line deltas). No `app/pdf/`, `app/services/pdp.py`, `app/api/pdp.py`,
  `app/main.py`, `app/bootstrap.py`, `app/app_state.py`, or dashboard files modified — the concurrency
  notice is honored, no in-progress P8 source leaked into this change.
- **Fix is correct and minimal.** `reportlab` is a genuine runtime dep (`pyproject.toml:42`
  `reportlab>=4.0.0`) imported at module scope (`app/pdf/builder.py:26-29`), reachable from `app.main`
  via `app/services/pdp.py:53` → `app/api/pdp.py:43`, so pytest hits it at collection for nearly every
  test file. Adding it to the curated `uv pip install` line resolves the 23 collection errors. This is the
  same recurring "curated CI venv missing a newly-added light dep" class as FIX-01/02/03/04/09; the shape
  matches precedent.
- **Sync invariant preserved.** The two curated install lines (CI `backend-ci.yml:118-121` and
  `Makefile:55-58`) are byte-identical after normalizing indentation — they will produce the same venv, as
  the workflow comment requires. `reportlab` correctly placed in the light tier next to
  joserfc/authlib/langgraph, not the deliberately-excluded ML stack (torch/sentence-transformers/docling).
- **Comment quality good.** The per-dependency explanatory block is extended in the existing one-sentence
  style (who imports it / why light / why must-curate) — leaves the next maintainer the context to avoid
  repeating the gap.
- Engineer's local reproduction (curated-venv style, `--no-sync`) reports ruff/format/mypy green and
  `719 passed, 62 skipped`, zero collection errors; 62 skips are the live-DB suites (no Postgres locally),
  consistent with `make test`. Not independently re-run here — a CI-config-only change with a verified
  diff and matching lists; rerunning the full suite risks pulling in the concurrent uncommitted P8 work,
  which the task explicitly says not to gate on.
