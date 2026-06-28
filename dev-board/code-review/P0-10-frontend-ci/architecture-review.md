# Architecture review — P0-10-frontend-ci · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure / frontend home | Frontend lives in its own module; v2 frontend at `frontend-v2/` (blessed coexistence, §8 path `frontend/` is the P11 cutover target) | Workflow + Jest config + stub test all scoped under `frontend-v2/`; `working-directory: frontend-v2`; path filter `frontend-v2/**` | None — correct location; no premature rename to `frontend/`. |
| A2 | §3 tech stack | Next.js (App Router) + React + TypeScript | CI runs `next lint` + `tsc --noEmit` + Jest against the Next 15.5.x App-Router app (root `app/` layout, React 19, TS 5) | None — §3 pins no major version; consistent with the P0-05 scaffold. |
| A3 | P0 plan CI line | "CI: lint/format/type (… eslint/tsc frontend) + test stubs" (plan.md L27) | Single `frontend` job: install → lint → type-check → test, plus one rendering stub test | Fully satisfies the P0 CI item for the frontend. |
| A4 | Test path vs task spec | task.md asked for `src/__tests__/page.test.tsx` | Placed at `frontend-v2/__tests__/page.test.tsx` because the scaffold has no `src/` dir (root `app/` router) | Accepted deviation — matching the real scaffold is the right call; inventing a lone `src/` would fork the layout. Logged, no change. |
| A5 | CI consistency / posture | Mirror established `backend-ci.yml` shape | Same triggers (`push`/`pull_request` on `main`+`version-2`), `concurrency` cancel, `permissions: contents: read`, path filtering, `defaults.run.working-directory` | None — CI conventions stay uniform across the two workflows. |

## Cross-cutting checks
- [x] Fits target structure (§8) — frontend work confined to `frontend-v2/`; backend untouched. Layering (Router→Service→Agent/Repo) N/A (frontend tooling/CI only).
- [x] Honors locked decisions — no backend stack surface touched; no ReAct parser / datastore / auth / embedding implications. N/A by scope.
- [x] Interfaces-before-implementations — N/A (CI/tooling task, no runtime seams).
- [x] Budget posture respected — free GitHub Actions + OSS toolchain; npm cache, `concurrency` cancel, and path filters minimize CI minutes; `next/jest` (SWC) avoids extra transform deps.

## Notes
- No secrets in the workflow; `permissions: contents: read` is least-privilege. Good.
- `@/*` alias is consistent across three places (tsconfig `paths`, Jest `moduleNameMapper`, the test's `@/app/page` import) and resolves to the real heading in `app/page.tsx` — the seam is coherent.
- Follow-up (not blocking, owned later): `next lint` is deprecated in Next 16; the engineer correctly deferred the ESLint-CLI migration to the Node-20/Next-16 upgrade. Track it there, not here.
- Reminder for P11: when `frontend-v2/` is renamed to `frontend/` at cutover, this workflow's `paths`, `working-directory`, and `cache-dependency-path` must move with it. Cheap to do at that point; do not pre-empt now.

## Verdict: APPROVED
