---
name: check-frontend-ci-tasks
description: Checklist for reviewing frontend (Next.js) CI/Jest setup tasks in frontend/
metadata:
  type: project
---

Reviewing a frontend CI / Jest-setup task (GitHub Actions workflow + Jest config + stub test).

NOTE: the frontend dir was renamed `frontend-v2/` → `frontend/` in P0-13 (2026-06-28). Paths below say `frontend/`; older review files still cite `frontend-v2/` as historical record.

**Why:** these gate on the three checks actually passing reproducibly in CI, plus no artifacts/secrets committed — not on logic.

**How to apply — concrete checks (run from `frontend/`, node_modules is present):**
- `npm run lint` (→ `next lint`), `npm run type-check` (→ `tsc --noEmit`), `npm test -- --watchAll=false` must all pass. Reproduce them; don't trust the engineer's pasted output.
- `npm ci` must succeed = `package-lock.json` in sync. This is CI's reproducibility gate; verify it.
- `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/frontend-ci.yml'))"` for YAML validity.
- Workflow security: least-privilege `permissions: contents: read`; uses `pull_request` NOT `pull_request_target` (latter exposes secrets to forks); no `secrets`/tokens referenced.
- `cache-dependency-path` for setup-node must be repo-root-relative (`frontend/package-lock.json`), because the cache step runs before `defaults.run.working-directory` applies. A bare `package-lock.json` there would be a real bug.
- Committed-artifacts check: `git add -n frontend | grep -v node_modules`. Confirm `.next`, `node_modules`, `*.tsbuildinfo`, `next-env.d.ts` are gitignored. Gotcha: `next/jest` (SWC transform) generates a `.swc/` cache dir that is NOT in the default Next .gitignore — flag as a nit (usually empty so not committed yet).
- tsconfig typically includes `**/*.ts(x)` so `tsc` type-checks tests + jest config. jest-dom matchers (`toBeInTheDocument`) type-resolve only because `jest.setup.ts` imports `@testing-library/jest-dom` AND is in the tsconfig include set — verify both if type-check is green.
- `next lint` only scans Next default dirs (app/components/lib/pages/src), so a test in `__tests__/` is NOT linted — nit, not a gate.
- Stack pins: Next 15.5.x / ESLint 8 / Jest 29 — `next lint` prints a "removed in Next 16" deprecation notice; harmless, not a finding.
- Don't gate on scaffold-path deviations (e.g. test at `__tests__/` vs task's literal `src/__tests__/`) — frontend uses root `app/` router, no `src/`; that's system-architect's lane.
