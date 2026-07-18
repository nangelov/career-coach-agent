# Task P8-07-cicd-verify — P8 CI/CD verification

- **Phase:** P8   **Status:** ENG   **Tags:** (T)

## Scope
tasks.md item: **CI/CD verification** — run the full backend + frontend CI command sets
locally (ruff + `ruff format --check` + mypy + pytest; eslint + tsc + jest — the exact
commands in `.github/workflows/backend-ci.yml` / `frontend-ci.yml`) and confirm both are
green before closing the phase.

This is the final P8 gate. All of P8-01..P8-06 are DONE and merged (plus the cross-cutting
`FIX-10-p8-ruff-format-debt` and `FIX-11-backend-ci-reportlab-missing` fixes that landed
during the phase). Read the two workflow files to get the **exact** command invocations
(flags, working directories, Python/Node versions, any service containers, the curated
dependency install list) — do not approximate them from memory/other tasks' reports; CI
config may have shifted since P7's equivalent verification (P7-06 + the two FIX tasks above
already touched it).

1. Run the backend CI command set exactly as `.github/workflows/backend-ci.yml` defines it
   (curated-venv dependency install, ruff check, ruff format --check, mypy, pytest — including
   whatever service containers / env vars that workflow wires for the live-DB-gated
   integration tests).
2. Run the frontend CI command set exactly as `.github/workflows/frontend-ci.yml` defines it
   (eslint, tsc, jest).
3. Backend CI's Postgres+pgvector service container step is present (P2-10): also do the full
   local live-container pass (mirrors `SEC-10-container-verify` / prior phases' pattern):
   `docker compose up -d db` (or the CI's equivalent), migrate to head, run the full suite so
   live-DB-gated tests execute instead of skip (this exercises P8-01's new migration/index and
   the P8-02/P8-04 Postgres-backed dashboard store integration tests against a real DB), then
   tear the container back down.
4. Fix the root cause of **any** red result — do not weaken or skip a test/lint rule to force
   green. If a failure traces back to a specific earlier P8 task's code, fix it in place and
   note which task it belongs to in your report.

## Acceptance criteria
- [ ] Backend: `ruff check`, `ruff format --check`, `mypy` (CI's scoped paths), `pytest` all
      green, run with the **exact** commands from `backend-ci.yml` (curated-venv install list,
      not a full `uv sync`).
- [ ] Frontend: `eslint`, `tsc`, `jest` all green, run with the **exact** commands from
      `frontend-ci.yml`.
- [ ] The live-DB integration pass (Postgres+pgvector service container, `docker compose up -d
      db` + migrate to head + full suite) is also run locally and green — not just the
      offline/skip-mode suite.
- [ ] Report states clearly: is P8 CI/CD fully green? If any fix was needed, which task's code
      and what was wrong.

## Design references
- `.github/workflows/backend-ci.yml`, `.github/workflows/frontend-ci.yml`
- Precedent: `dev-board/code-review/P7-06-cicd-verify/`, `dev-board/code-review/P6-10-cicd-verify/`,
  `dev-board/code-review/SEC-10-container-verify/`
- `dev-board/code-review/FIX-10-p8-ruff-format-debt/`, `dev-board/code-review/FIX-11-backend-ci-reportlab-missing/`
  — the two CI-curation fixes already applied during this phase; confirm they are still intact.

## Constraints / non-goals
- No new features — this task only makes existing P8 code pass the CI gate it will actually
  run under.
