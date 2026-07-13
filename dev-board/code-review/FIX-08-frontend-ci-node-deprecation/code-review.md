# Code review — FIX-08-frontend-ci-node-deprecation · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | `.github/workflows/*.yml` | Actions pinned to floating major tags (`@v7`, `@v6`) rather than commit SHAs — a supply-chain surface. | None required — matches the repo's established convention (`astral-sh/setup-uv@v5`, prior `@v4`). Noted only; do not gate. |

## Notes
- Diff is minimal and matches `engineer.md` exactly: `checkout@v4→v7`, `setup-node@v4→v6`, `node-version "20"→"22"` + step label in frontend-ci; `checkout@v4→v7` in backend-ci; `node:20-alpine→node:22-alpine` (all 3 stages) + comment in `frontend/Dockerfile`.
- Independently verified via `git ls-remote` that `actions/checkout@v7` (v7.0.0) and `actions/setup-node@v6` (v6.4.0) are the **current latest major tags** — the engineer's "verified not assumed" claim holds.
- `frontend/package.json` confirmed to have **no `engines` constraint** (would conflict); the CI-referenced scripts `lint`/`type-check`/`test`/`build` all exist.
- Node 22 is a current active LTS; correctly moves the language runtime off EOL Node 20, not just the action-runtime warning.
- backend-ci bump is justified (same `checkout@v4` emitted the identical deprecation warning) — not scope creep; `astral-sh/setup-uv@v5` correctly left alone.
- No unrelated workflow behavior changed (triggers/paths/concurrency/permissions/services untouched — confirmed against the diff).
- CI-infra only; no application code touched. Other files in `git status` (`.gitignore`, `backend/app/ingestion/data/*`, FIX-09 folder) belong to other in-flight tasks and are not part of this diff.
- Engineer's local suite run (Node 22.23.1: `npm ci`/lint/type-check/jest 151/151/build all green) is credible and consistent with the scripts present; not re-run here (host ships Node 18), but the change is a version-string bump with no logic risk.
