# Engineer report — P0-10-frontend-ci · Revision 1

## Summary
Added a GitHub Actions workflow that lints, type-checks, and unit-tests the `frontend/`
Next.js app on every push/PR to `main` and `version-2`. Wired up Jest for Next.js 15 +
TypeScript using the official `next/jest` (SWC) transform, added the required `test` and
`type-check` scripts, the test dev-dependencies, and one stub test that renders the home
page and asserts the "Career Coach v2" heading is present.

## Files changed
- `.github/workflows/frontend-ci.yml` — new CI workflow (single `frontend` job, steps:
  install → `next lint` → `tsc --noEmit` → `jest`), scoped to `frontend/**` + the
  workflow file, on push/PR to `main`/`version-2`, `working-directory: frontend`.
- `frontend/package.json` — added `test`/`type-check` scripts and dev deps:
  `jest`, `jest-environment-jsdom`, `@types/jest`, `@testing-library/react`,
  `@testing-library/jest-dom`, `@testing-library/dom`, `ts-node`.
- `frontend/jest.config.ts` — Jest config via `next/jest` (jsdom env, jest-dom setup,
  `@/*` module alias mirroring tsconfig).
- `frontend/jest.setup.ts` — imports `@testing-library/jest-dom` matchers.
- `frontend/__tests__/page.test.tsx` — stub test rendering `app/page.tsx`.
- `frontend/package-lock.json` — regenerated; verified in sync via `npm ci`.

## Key decisions
- **`next/jest` (SWC) instead of ts-jest/babel-jest** — official Next.js 15 testing path;
  no separate Babel/TS transform config, picks up `next.config` + SWC automatically. Task
  allowed `ts-jest` *or* a Next preset; the Next preset is the lower-maintenance choice.
  `ts-node` is included only so Jest can load the `jest.config.ts` file.
- **Test placed at `frontend/__tests__/page.test.tsx`, not `src/__tests__/...`** — the
  P0-05 scaffold uses the root `app/` router layout (no `src/` directory). Putting a lone
  `src/` dir just for the test would break the established layout and the `@/*` → `./*`
  alias. The home component lives at `app/page.tsx`, imported via `@/app/page`. Flagging
  this as a deliberate deviation from the literal path in the task. (app-design §3 stack.)
- **Single job with sequential steps, not three jobs** — shares one `npm ci` install
  instead of installing the dep tree 3× on a free CI tier (task explicitly permits
  "three jobs or steps"). Mirrors the existing `backend-ci.yml` shape (defaults.run
  working-directory, concurrency cancel, `permissions: contents: read`, path filter).
- **Node 20 in CI** — Next 15.5/Jest run on 18.18+, but Node 20 LTS is the safe modern
  target and silences the `eslint-visitor-keys` engine warning seen locally on Node 18.
  Per [[project-node-version]], the app stays pinned to Next 15.5.x / ESLint 8 regardless.
- **No secrets** — workflow has no `secrets`/tokens; only `contents: read`.

## How to verify
```bash
cd frontend
npm ci
npm run lint        # next lint → "No ESLint warnings or errors"
npm run type-check  # tsc --noEmit → no output (clean)
npm test -- --watchAll=false   # jest → 1 passed
```
Workflow YAML validates (`python3 -c "import yaml; yaml.safe_load(open('.github/workflows/frontend-ci.yml'))"`).

## Self-check
- [x] Meets acceptance criteria:
  - `.github/workflows/frontend-ci.yml` exists, valid YAML.
  - `npm run lint` → "No ESLint warnings or errors".
  - `npx tsc --noEmit` → zero errors.
  - `npm test -- --watchAll=false` → stub test passes (1/1).
  - Triggers on push + pull_request targeting `main` and `version-2`.
  - All CI run steps use `working-directory: frontend`.
  - No secrets in the workflow.
- [x] No secrets committed; layering N/A (frontend tooling/CI only).
- [x] `npm ci` succeeds → lockfile in sync for CI.
- [x] Tests/lints pass (results pasted above).

## Notes / flag for reviewers
- Test path deviates from the literal `src/__tests__/...` in the task to match the actual
  root-`app/` scaffold — see Key decisions. If a `src/` layout is desired, that is a
  larger scaffold change beyond this task.
- `next lint` prints a deprecation notice (removed in Next 16); harmless on the pinned
  Next 15.5.x. Migrating to the ESLint CLI is deferred until the Node-20/Next-16 upgrade.
- `npm install` reports moderate transitive dev-dep advisories (jsdom chain); no runtime
  impact and out of scope (no audit gate requested).
