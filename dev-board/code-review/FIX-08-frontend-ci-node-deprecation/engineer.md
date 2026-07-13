# Engineer report — FIX-08-frontend-ci-node-deprecation · Revision 1

## Summary
Bumped `frontend-ci` off the deprecated Node-20 action runtime and off the deprecated Node-20
language runtime. `actions/checkout` and `actions/setup-node` moved to their current latest majors
(which run on the Node 24 runtime, silencing the deprecation warning), and the frontend is now
built/tested under Node 22 (active LTS). Bumped `backend-ci`'s `actions/checkout` in lockstep
(same `@v4` emits the identical warning) and the frontend `Dockerfile` base image `node:20` → `node:22`
so the container runtime matches CI. No application code changed.

## Files changed
- `.github/workflows/frontend-ci.yml` — `checkout@v4→v7`, `setup-node@v4→v6`, `node-version "20"→"22"`, step-name label updated.
- `.github/workflows/backend-ci.yml` — `checkout@v4→v7` (consistency; same deprecating action).
- `frontend/Dockerfile` — `node:20-alpine → node:22-alpine` across all three stages (deps/builder/runner) + comment updated.

## Key decisions
- **Latest majors, verified not assumed.** Task said bump each action to its *latest major* and verify
  rather than assume v5. Verified via GitHub releases: `actions/checkout` latest major = **v7** (v7.0.0),
  `actions/setup-node` latest major = **v6** (v6.4.0). Both major tags resolve (HTTP 200) and run on the
  Node 24 runtime, which removes the "Node.js 20 is deprecated" warning. checkout v7's only breaking change
  (blocking fork-PR checkout for `pull_request_target`/`workflow_run`) does not affect this workflow — it
  uses plain `push`/`pull_request` with a no-arg checkout. `setup-node` `node-version` + `cache: npm` inputs
  are unchanged across v4→v6.
- **node-version "22".** Node 20 is itself EOL/deprecated; 22 is the current active LTS (`v22.23.1 "Jod"`).
  `frontend/package.json` has **no `engines` constraint** to conflict; Next 15.5 requires Node >=18.18.
- **backend-ci checkout bumped too.** Task item 3 said use judgement. `backend-ci`'s `checkout@v4` emits the
  *same* Node-20 deprecation warning, so bumping it is a real fix, not churn. Left `astral-sh/setup-uv@v5`
  untouched — not the flagged action and out of scope.
- **Dockerfile bumped (item 4).** Trivial base-image tag change (`node:20-alpine`→`node:22-alpine`) keeps the
  container Node in lockstep with CI. Verified `next build` succeeds under Node 22.
- Triggers / paths / concurrency / permissions / services left unchanged.

## How to verify
- Inspect the three diffs above.
- Under Node 22 in `frontend/`: `npm ci && npm run lint && npm run type-check && npm test -- --watchAll=false` (and `npm run build`).
- Confirm `actions/checkout@v7` / `actions/setup-node@v6` major tags exist on GitHub.

## Tests (final step — mandatory)
Ran the full frontend suite under a locally-installed **Node v22.23.1** (host only ships Node 18; downloaded
the v22 LTS tarball to scratchpad and put it on PATH):
- `npm ci` — clean install from lockfile (2 moderate audit advisories pre-existing, unrelated to this task).
- `npm run lint` (`next lint`) — ✔ No ESLint warnings or errors.
- `npm run type-check` (`tsc --noEmit`) — clean, no output.
- `npm test -- --watchAll=false` (jest) — **16 suites, 151/151 tests passed**.
- `npm run build` (`next build`) — succeeded (validates the bumped Dockerfile build path under Node 22).

All green; no failures to root-cause.

## Self-check
- [x] Meets acceptance criteria (no deprecated action/runtime combo; `node-version` = active LTS 22; suite green under Node 22; triggers/concurrency/permissions untouched; backend-ci + Dockerfile calls noted).
- [x] No secrets committed; CI/infra-only, no application/layering changes.
- [x] Tests/lints pass under Node 22 (results pasted above).

## Notes
- Other files in `git status` (`.gitignore`, `backend/app/ingestion/data/*`, `queue.md`, FIX-09 folder) belong
  to other in-flight tasks in this shared worktree — untouched by this task.
