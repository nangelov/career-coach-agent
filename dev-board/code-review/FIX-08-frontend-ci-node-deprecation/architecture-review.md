# Architecture review — FIX-08-frontend-ci-node-deprecation · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | No source-module moves; work confined to CI/infra (`.github/workflows/*`, `frontend/Dockerfile`) | Only `frontend-ci.yml`, `backend-ci.yml`, `frontend/Dockerfile` touched — no `api/`/`agents/`/`repositories/`/etc. changes | None |
| A2 | Budget posture (§11 free/OSS/self-hosted) | No new paid/managed CI dependency | Pure version bumps of first-party GitHub-published actions + Node LTS; no new services | None |
| A3 | Locked-stack neutrality | Frontend = Next.js App Router; Node runtime a supported LTS | `node-version "22"` + `node:22-alpine` across all three Dockerfile stages; Next 15.5 floor (>=18.18) satisfied; CI and container runtime kept in lockstep | None |
| A4 | Consistency across CI surfaces | If the same deprecating action is pinned elsewhere, move in lockstep | `backend-ci.yml` `checkout@v4→v7` bumped for the identical Node-20 warning; `astral-sh/setup-uv@v5` correctly left untouched (not flagged, out of scope) | None |
| A5 | No behavioral drift | Triggers/paths/concurrency/permissions/services unchanged (§ non-goals) | `on:`/`paths`/`concurrency`/`permissions`/`services` blocks in both workflows unchanged; only step `uses:`/`node-version`/label edits | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — infra-only, no source touched, no layering impact
- [x] Honors locked decisions — no ReAct parser / Postgres+Redis / SSO / embeddings surfaces touched; Next.js + self-hosted posture intact
- [x] Interfaces-before-implementations — N/A (no seams affected)
- [x] Budget posture respected — free/OSS runners and actions only

## Notes
- Design-neutral maintenance task; no persistent design ruling warranted. Latest-major choices (checkout v7, setup-node v6) and the backend-ci lockstep bump are sound and appropriately scoped — the engineer correctly declined to expand into unrelated actions.
- `docker-compose.yml` builds the frontend from this Dockerfile (no independent hard-coded `node:20` reference), so no additional lockstep change is required. Nothing further to unwind later.
