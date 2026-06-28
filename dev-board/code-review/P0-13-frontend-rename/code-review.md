# Code review — P0-13-frontend-rename · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | frontend/package.json:2 (and frontend/package-lock.json:2,8) | The npm package `"name": "career-coach-frontend-v2"` still literally contains `frontend-v2`, so acceptance criterion "zero remaining occurrences of `frontend-v2`" is not literally met for files inside `frontend/`. The engineer left it deliberately because the explicit non-goal forbids modifying source inside `frontend/` and the string is a product/package name, not a path. No functional impact (the name is not a path/resolution key; build, type-check, test, `npm ci` all pass regardless). | Orchestrator/architect call only — the "zero occurrences" criterion and the "don't touch frontend source" non-goal directly conflict here. If consistency wins, rename to `career-coach-frontend` in `package.json` and the two root `name` fields of `package-lock.json` together (trivial, safe). Otherwise defer and accept as the product-name reading. Not a correctness/security gate. |

## Notes
- **Functional acceptance — all verified by re-running, not trusting the report:**
  - `frontend/` exists at repo root; `frontend-v2/` is gone (`ls` confirms).
  - `docker compose config` → VALID. The `frontend` service build `context: ./frontend` is correct; `frontend/Dockerfile` present and uses only relative paths (no `frontend-v2` baked in).
  - `npm run type-check` (`tsc --noEmit`) → clean, no output.
  - `npm run build` → "✓ Generating static pages (4/4)", routes `/` and `/_not-found` prerendered, 0 errors.
  - `npm test -- --watchAll=false` → 1 suite / 1 test passed.
  - `.github/workflows/frontend-ci.yml`: `paths` filters, `working-directory: frontend`, and `cache-dependency-path: frontend/package-lock.json` (repo-root-relative, required because the setup-node cache step runs before `defaults.run.working-directory` applies) all correct.
- **Remaining `frontend-v2` hits outside `frontend/` are all correctly out of scope and not gated:**
  - Reviewer-authored audit records (`dev-board/code-review/*/{code-review,architecture-review}.md`) — protected by the skill's "never edit another agent's section"; they are historical and were accurate when written. Correct to leave.
  - `P0-13-frontend-rename/task.md` and the `queue.md` P0-13 row — self-referential descriptions of this rename task; orchestrator-owned.
  - `.claude/agent-memory/{system-architect,code-reviewer}/*` — other/own agent private memory, curated by the owning agent (I am updating my own code-reviewer memory separately to drop the stale `frontend-v2` path).
- **`git mv` vs `mv`:** the engineer's rationale checks out — `frontend-v2/` was entirely untracked on `version-2` (only `docker-compose.yml` is tracked), so `git mv` cannot run and there is no history to lose. The rename was a true move, not copy+delete. Acceptance intent satisfied.
- No backend code touched; no secrets introduced. Deletion of gitignored `.next`/`.swc` caches before the rename is sound (they bake stale absolute paths) and keeps the grep clean.
