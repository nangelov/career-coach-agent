# Task FIX-08-frontend-ci-node-deprecation — bump frontend-ci off deprecated Node 20
- **Phase:** cross-cutting (CI/infra)   **Status:** ENG   **Tags:** (I)

## Scope
GitHub Actions now emits this deprecation warning on `frontend-ci` runs:

```
Node.js 20 is deprecated. The following actions target Node.js 20 but are being forced to run
on Node.js 24: actions/checkout@v4, actions/setup-node@v4.
```

`.github/workflows/frontend-ci.yml` pins `actions/checkout@v4`, `actions/setup-node@v4`, and
`node-version: "20"` (the Node version the frontend build/tests actually run under, which is a separate
concern from the action-runtime warning but also worth fixing since Node 20 itself is EOL/deprecated).

Fix:
1. Bump `actions/checkout@v4` → the latest major (`v5` at time of writing — verify current latest via the
   marketplace/changelog rather than assuming) and `actions/setup-node@v4` → its latest major, so the actions
   themselves run on a current Node runtime and the warning disappears.
2. Bump `node-version: "20"` to a current active LTS (e.g. `"22"`) so the frontend is actually built/tested
   under a supported Node version, not just silencing the action-runtime warning while still testing on a
   deprecated language runtime. Confirm `frontend/package.json` has no `engines` constraint that conflicts, and
   that `npm ci` / `next build` / `next lint` / `jest` all still run cleanly under the bumped version.
3. Check `backend-ci.yml` too — it does not use `actions/setup-node`, but confirm its `actions/checkout@v4`
   doesn't need the same bump for consistency (only bump if there's a real reason; don't touch it if it's not
   flagged and bumping would be pure churn beyond this task's scope — use judgement, note your call in the
   report).
4. Check `Dockerfile`(s) / `docker-compose.yml` for any hard-coded Node 20 base image reference that should
   move in lockstep (only if trivially in scope — flag rather than expand scope if it's a bigger change).

## Acceptance criteria
- [ ] `frontend-ci.yml` no longer targets a deprecated action/runtime combination; `node-version` is a current
      active LTS.
- [ ] Full frontend test suite (`npm ci`, `npm run lint`, `npm run type-check`, `npm test -- --watchAll=false`)
      passes locally under the bumped Node version.
- [ ] No unrelated workflow behavior changes (paths/triggers/concurrency/permissions untouched).
- [ ] Report notes whether `backend-ci.yml` / Dockerfiles needed any related change, and why or why not.

## Design references
- `.github/workflows/frontend-ci.yml`, `.github/workflows/backend-ci.yml`
- GitHub's Node 20 deprecation notice: https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/

## Constraints / non-goals
- CI/infra-only — no application code changes.
