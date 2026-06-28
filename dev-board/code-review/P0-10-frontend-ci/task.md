# Task P0-10-frontend-ci — Frontend CI: eslint + tsc + test stubs

- **Phase:** P0   **Status:** ENG   **Tags:** (I)

## Scope

Set up a GitHub Actions workflow for the `frontend/` Next.js app that runs on every push/PR:

1. **`.github/workflows/frontend-ci.yml`** — workflow with three jobs (or steps):
   - **lint**: `npm run lint` (ESLint via `next lint`)
   - **typecheck**: `npx tsc --noEmit`
   - **test**: `npm test -- --watchAll=false` (Jest, runs any stub tests)

2. Ensure `frontend/` has a valid `jest.config.ts` (or `jest.config.js`) configured for Next.js + TypeScript using `@testing-library/react` + `jest-environment-jsdom`.

3. Add **one stub test** `frontend/src/__tests__/page.test.tsx` that renders the home page component and asserts the "Career Coach v2" heading is present.

4. Ensure `package.json` `scripts` includes:
   - `"lint": "next lint"`
   - `"test": "jest"`
   - `"type-check": "tsc --noEmit"`

5. Add necessary dev dependencies if missing: `jest`, `@types/jest`, `@testing-library/react`, `@testing-library/jest-dom`, `jest-environment-jsdom`, `ts-jest` (or `babel-jest` with Next.js preset).

## Acceptance criteria

- [ ] `.github/workflows/frontend-ci.yml` exists and is valid YAML.
- [ ] `npm run lint` passes with zero errors in `frontend/`.
- [ ] `npx tsc --noEmit` passes with zero TypeScript errors.
- [ ] `npm test -- --watchAll=false` runs the stub test and passes.
- [ ] CI workflow triggers on `push` and `pull_request` targeting `main` and `version-2`.
- [ ] Working directory for all CI steps is `frontend/`.
- [ ] No secrets in the workflow file.

## Design references

- `dev-board/plan.md` — P0 "CI: Frontend CI: eslint + tsc + test stubs"
- `dev-board/app-design-and-features.md` — §3 tech stack (Next.js 14, TypeScript)
- `frontend/` scaffold (P0-05)

## Constraints / non-goals

- No E2E tests (Playwright/Cypress) in this task.
- No coverage thresholds.
- Backend CI is a separate workflow (P0-09, done).
- Do not run `docker compose` in this CI workflow.
