# Task P7-06-cicd-verify — P7 CI/CD verification

- **Phase:** P7   **Status:** ENG   **Tags:** (T)

## Scope
tasks.md item: **CI/CD verification** — run the full backend + frontend CI command sets
locally (ruff + `ruff format --check` + mypy + pytest; eslint + tsc + jest — the exact
commands in `.github/workflows/backend-ci.yml` / `frontend-ci.yml`) and confirm both are
green before closing the phase.

This is the final P7 gate. All of P7-01..P7-05 are DONE and merged. Read the two workflow
files to get the **exact** command invocations (flags, working directories, Python/Node
versions, any service containers) — do not approximate them from memory/other tasks' reports;
CI config may have shifted since P6's equivalent verification.

1. Run the backend CI command set exactly as `.github/workflows/backend-ci.yml` defines it
   (ruff check, ruff format --check, mypy, pytest — including whatever service containers /
   env vars that workflow wires for the live-DB-gated integration tests, if it runs them).
2. Run the frontend CI command set exactly as `.github/workflows/frontend-ci.yml` defines it
   (eslint, tsc, jest).
3. If backend CI's Postgres+pgvector service container step is present, also do the full
   local live-container pass (mirrors `SEC-10-container-verify` / prior phases' pattern):
   `docker compose up -d db` (or the CI's equivalent), migrate to head, run the full suite so
   live-DB-gated tests execute instead of skip, then tear the container back down.
4. Fix the root cause of **any** red result — do not weaken or skip a test/lint rule to force
   green. If a failure traces back to a specific earlier P7 task's code, fix it in place and
   note which task it belongs to in your report.

## Acceptance criteria
- [ ] Backend: `ruff check`, `ruff format --check`, `mypy` (CI's scoped paths), `pytest` all
      green, run with the **exact** commands from `backend-ci.yml`.
- [ ] Frontend: `eslint`, `tsc`, `jest` all green, run with the **exact** commands from
      `frontend-ci.yml`.
- [ ] If backend CI runs live-DB integration tests via a service container, that pass is also
      run locally and green (not just the offline/skip-mode suite).
- [ ] Report states clearly: is P7 CI/CD fully green? If any fix was needed, which task's
      code and what was wrong.

## Design references
- `.github/workflows/backend-ci.yml`, `.github/workflows/frontend-ci.yml`
- Precedent: `dev-board/code-review/P6-10-cicd-verify/`, `dev-board/code-review/SEC-10-container-verify/`

## Constraints / non-goals
- No new features — this task only makes existing P7 code pass the CI gate it will actually
  run under.
