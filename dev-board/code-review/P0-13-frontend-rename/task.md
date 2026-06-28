# Task P0-13-frontend-rename — Rename frontend-v2/ → frontend/ and fix all references

- **Phase:** P0   **Status:** ENG   **Tags:** (F)(I)

## Scope

Now that the v1 CRA frontend has been moved to `legacy-code/`, `frontend-v2/` is the **only** frontend.
Rename it to `frontend/` and fix every reference across the codebase.

### Steps
1. `git mv frontend-v2 frontend` — rename the directory (preserving git history).
2. Update **all** references to `frontend-v2` → `frontend` in:
   - `docker-compose.yml` (build context, service name if applicable)
   - `.github/workflows/frontend-ci.yml` (working-directory, paths)
   - `CLAUDE.md`
   - Any `dev-board/` docs that mention `frontend-v2/`
   - Any `dev-board/code-review/*/task.md` or `engineer.md` files referencing `frontend-v2`
   - `legacy-code/README.md` if it mentions `frontend-v2`
3. Verify the rename didn't break anything:
   - `docker compose config` still validates.
   - `cd frontend && npm run build` succeeds (zero errors).
   - `cd frontend && npm test -- --watchAll=false` passes.

## Acceptance criteria

- [ ] `frontend/` exists at repo root; `frontend-v2/` is gone.
- [ ] `git mv` used (history preserved, not a copy+delete).
- [ ] `docker compose config` validates without errors.
- [ ] `npm run build` (from `frontend/`) completes with zero TypeScript/ESLint errors.
- [ ] `npm test -- --watchAll=false` (from `frontend/`) passes.
- [ ] Zero remaining occurrences of `frontend-v2` anywhere in the repo (grep check).
- [ ] `.github/workflows/frontend-ci.yml` uses `frontend/` as working directory.

## Design references

- `dev-board/app-design-and-features.md` — §8 frontend structure (Next.js App Router)
- `dev-board/plan.md` — P11 note about `frontend-v2 → frontend` rename at cutover (now done early)
- `docker-compose.yml` — frontend service build context (P0-06)
- `.github/workflows/frontend-ci.yml` — frontend CI (P0-10)

## Constraints / non-goals

- Do NOT modify any source files inside `frontend/` beyond the rename itself.
- Do NOT touch `legacy-code/frontend/` (the old CRA — leave it in place).
- Do NOT change any backend code.
