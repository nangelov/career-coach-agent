# Engineer report — P0-13-frontend-rename · Revision 1

## Summary
Renamed the v2 frontend directory `frontend-v2/` → `frontend/` (it is now the only frontend, since v1
CRA was moved to `legacy-code/`) and fixed every live path reference across config, CI, docs, and the
dev-board task records. Validated the rename with `docker compose config`, `npm run build`, type-check,
and the Jest suite — all green.

## Files changed
- `frontend-v2/` → `frontend/` — directory rename (the whole Next.js App Router app).
- `docker-compose.yml` — `frontend` service build `context: ./frontend-v2` → `./frontend` (tracked file; service name was already `frontend`).
- `.github/workflows/frontend-ci.yml` — `paths` filters, `working-directory`, `cache-dependency-path`, and the header comment all `frontend-v2` → `frontend`.
- `legacy-code/README.md` — two `frontend-v2/` mentions → `frontend/`.
- `dev-board/code-review/{P0-05,P0-06,P0-10,P0-11,P0-12}-*/task.md` and `engineer.md` — `frontend-v2` → `frontend` (per task step 2, scoped to task.md/engineer.md).
- `.claude/agent-memory/fullstack-engineer/project-node-version.md` — updated my own memory to reflect the new `frontend/` path (curation).
- Deleted `frontend-v2/.next` and `.swc` (gitignored build cache holding stale absolute paths) before the rename; `npm run build` regenerated `frontend/.next` cleanly.

## Key decisions
- **Plain `mv`, not `git mv`.** `frontend-v2/` is entirely **untracked** on this branch (only `docker-compose.yml` is git-tracked; `dev-board/`, `frontend-v2/`, `.github/`, `backend/`, `.claude/agent-memory/` are all `??`). `git mv` aborts with `fatal: source directory is empty` because there are no tracked files to move. There is therefore no git history to preserve — plain `mv` is equivalent. (Acceptance criterion "git mv used / history preserved" is satisfied to the extent possible: nothing was a copy+delete, and no tracked history exists to lose.)
- **Deleted `.next`/`.swc` build cache before renaming.** These gitignored artifacts baked the old absolute `…/frontend-v2/…` paths into trace/manifest files; rebuilding from `frontend/` regenerated them with the correct paths, keeping the grep clean.
- **dev-board reviewer-authored files left untouched.** Task step 2 explicitly scopes the code-review folders to `task.md` and `engineer.md` only — it does **not** list `code-review.md` / `architecture-review.md`, and the agent-handoff skill states "Never edit another agent's section." Those files are historical audit records that were *accurate as written* (they describe *why* `frontend-v2/` was the blessed coexistence path at P0-05–P0-12). I left them as-is.

## Remaining `frontend-v2` occurrences (all intentional — see acceptance note below)
Repo-wide grep (excl. `node_modules`, `.git`) leaves only these justified buckets:
1. **`frontend/package.json` + `package-lock.json`** — `"name": "career-coach-frontend-v2"`. **Not changed**: the explicit non-goal forbids modifying source files inside `frontend/` beyond the rename, and the name reads as the *product* "v2" (Career Coach Agent v2), not a directory path. Trivial to change if a reviewer rules otherwise — flagging for adjudication since this is the one spot where "zero occurrences" and "don't touch frontend source" directly conflict.
2. **`dev-board/code-review/*/{code-review,architecture-review}.md`** — reviewer-authored audit records, out of task scope (see Key decisions) and protected by the skill's don't-edit-others'-files rule.
3. **`dev-board/code-review/P0-13-frontend-rename/task.md`** and **`queue.md` P0-13 row** — self-referential descriptions of *this rename task*; they must name `frontend-v2` to make sense (orchestrator-owned).
4. **`.claude/agent-memory/code-reviewer/*` and `system-architect/*`** — other agents' private curated memory (the system-architect note literally tracks "rename owed at P11"). Ownership belongs to those agents; left for them to re-curate. I updated only my own fullstack-engineer memory.

## How to verify
```bash
# rename landed
ls -d frontend && ! ls -d frontend-v2 2>/dev/null

# config still valid
docker compose config >/dev/null && echo OK

# from frontend/
cd frontend
npm run type-check          # tsc --noEmit, clean
npm run build               # Next 15.5.19, "Compiled successfully", 0 errors
npm test -- --watchAll=false   # 1 suite / 1 test passes

# workflow uses frontend/ as working dir
grep -n 'working-directory: frontend' ../.github/workflows/frontend-ci.yml
```
Results obtained:
- `docker compose config` → **VALID**.
- `npm run type-check` → clean (no output).
- `npm run build` → `✓ Compiled successfully in 4.9s`; routes `/` and `/_not-found` prerendered; **0 errors**.
- `npm test -- --watchAll=false` → `Test Suites: 1 passed`, `Tests: 1 passed`.
- `frontend/.next` post-build contains **no** `frontend-v2` references.

## Self-check
- [x] Meets acceptance criteria — `frontend/` exists, `frontend-v2/` gone, compose validates, build/test pass, workflow uses `frontend/`. ("Zero occurrences" met for all live code/config + task-scoped files; remaining hits are the 4 justified buckets above, flagged for review.)
- [x] No secrets committed; layering N/A (frontend-only rename, no backend code touched).
- [x] Tests/lints pass (results pasted above).
- [x] No source files inside `frontend/` modified beyond the rename (non-goal respected; `package.json` name flagged, not changed).

## Response to review (revisions only)
- n/a (revision 1)
