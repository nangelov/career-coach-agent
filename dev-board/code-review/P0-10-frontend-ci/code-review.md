# Code review — P0-10-frontend-ci · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | frontend-v2/.gitignore | The `next/jest` SWC transform generates a `frontend-v2/.swc/` cache dir that is **not** gitignored (verified: `git check-ignore` reports NOT IGNORED). It is empty right now so nothing leaks into a commit today, but once Jest writes a plugin cache there it would get committed. | Add `/.swc/` (and optionally `/coverage`, already present) to `frontend-v2/.gitignore`. Non-blocking. |
| C2 | nit | .github/workflows/frontend-ci.yml:49 | `next lint` only scans Next's default dirs (`app/`, `components/`, `lib/`, `pages/`, `src/`); the stub at `__tests__/page.test.tsx` and the root config files (`jest.config.ts`, `jest.setup.ts`) are **not** linted. CI is green but lint coverage excludes test code. | Optional: lint tests too via `next lint --dir app --dir components --dir lib --dir __tests__` or migrate to a flat ESLint config. Defer is fine. |
| C3 | nit | frontend-v2/__tests__/page.test.tsx | Test lives at `frontend-v2/__tests__/...`, not the literal `frontend-v2/src/__tests__/...` named in task scope item 3. | None — the scaffold (P0-05) uses the root `app/` router with no `src/` dir and the `@/* → ./*` alias; the engineer's placement is the correct match. Acceptance criterion 4 only requires the stub to run+pass, which it does. Noted for the record. |

## Notes
Verified independently from the repo (Node 18.19.1 locally; CI pins Node 20):
- `npm run lint` → "No ESLint warnings or errors" (deprecation notice only, harmless on pinned Next 15.5.x).
- `npm run type-check` (`tsc --noEmit`) → exit 0, zero errors. tsconfig includes the test + config `.ts`/`.tsx`, and the jest-dom global augmentation (imported in `jest.setup.ts`, which is in the include set) resolves `toBeInTheDocument()` cleanly.
- `npm test -- --watchAll=false` → 1 suite / 1 test passed; the stub renders `app/page.tsx` and asserts the "Career Coach v2" heading by role.
- `npm ci` → succeeds, so `package-lock.json` is in sync (CI's reproducibility gate holds).
- Both workflow files parse as valid YAML.

Workflow quality is good:
- Triggers on `push` + `pull_request` to `main` and `version-2`, path-filtered to `frontend-v2/**` + the workflow file (matches scope; saves CI minutes).
- `working-directory: frontend-v2` via `defaults.run`; `cache-dependency-path` correctly points at the repo-root-relative `frontend-v2/package-lock.json` (the setup-node cache step runs before `defaults.run` applies, so the relative path is required and correct).
- Least-privilege `permissions: contents: read`; `concurrency` cancel-in-progress with a frontend-specific group (won't collide with backend-ci). Uses `pull_request` (not `pull_request_target`), so no fork-secret exposure. No secrets/tokens referenced anywhere — acceptance criterion 7 satisfied.
- Shape mirrors the existing `backend-ci.yml`, which is the right consistency call.

Acceptance criteria 1–7 all met. No blocker/major/minor defects; only the three nits above, none of which gate.
