# Task P9-11-cicd-verify — P9 CI/CD verification

- **Phase:** P9   **Status:** ENG   **Tags:** (T)

## Scope
tasks.md item: **CI/CD verification** — run the full backend + frontend CI command sets
locally (ruff + `ruff format --check` + mypy + pytest; eslint + tsc + jest — the exact
commands in `.github/workflows/backend-ci.yml` / `frontend-ci.yml`) and confirm both are
green before closing the phase.

This is the final P9 gate. P9-01..P9-10 are all DONE. P9 added a large amount of new backend
surface (memory store/learn/recall/gdpr-filter modules, message-feedback, retention purge, a
new Celery beat service, a new migration) and new frontend surface (memory panel, message
feedback client) — read the two workflow files to get the **exact** command invocations
(flags, working directories, curated dependency install list, service containers) — do not
approximate from memory; the curated-dependency-install lists in CI have needed fixes in nearly
every prior phase (see `FIX-01`, `FIX-03`, `FIX-09`, `FIX-11`, `P8-08-curated-deps-guard`) —
**specifically check whether `langmem` and any of its transitive deps (e.g. `trustcall`) are
in the CI curated-install list**, since P9 is the first phase to actually import `langmem` at
runtime (P9-02 onward) rather than just declaring it in `pyproject.toml`.

1. Run the backend CI command set exactly as `.github/workflows/backend-ci.yml` defines it
   (curated-venv dependency install, ruff check, ruff format --check, mypy, pytest — including
   whatever service containers / env vars that workflow wires for the live-DB-gated
   integration tests, and the new Celery `beat` addition from P9-08 if CI touches
   docker-compose at all).
2. Run the frontend CI command set exactly as `.github/workflows/frontend-ci.yml` defines it
   (eslint, tsc, jest).
3. Full local live-container pass (mirrors `SEC-10-container-verify` / prior phases' pattern):
   `docker compose up -d db redis` (or CI's equivalent), migrate to head (confirm the new
   `message_feedback` uniqueness migration from P9-01 and any P9-08 migration apply cleanly),
   run the full suite so live-DB-gated tests execute instead of skip — this must include the
   P9-10 `test_p9_exit_verification.py` live-Postgres suite actually running, not skipping.
   Tear the container back down after.
4. Fix the root cause of **any** red result — do not weaken or skip a test/lint rule to force
   green. If a failure traces back to a specific earlier P9 task's code, fix it in place and
   note which task it belongs to in your report.

## Acceptance criteria
- [ ] Backend: `ruff check`, `ruff format --check`, `mypy` (CI's scoped paths), `pytest` all
      green, run with the **exact** commands from `backend-ci.yml` (curated-venv install list,
      not a full `uv sync`).
- [ ] Frontend: `eslint`, `tsc`, `jest` all green, run with the **exact** commands from
      `frontend-ci.yml`.
- [ ] The live-DB integration pass (Postgres+pgvector service container, migrate to head, full
      suite including `test_p9_exit_verification.py` actually executing against live Postgres)
      is also run locally and green.
- [ ] Explicit confirmation (pass/fail) that `langmem` + its runtime transitive dependencies are
      present in the CI curated-install list and that a CI-fresh environment can actually
      `import langmem` / the P9 memory modules — this is the most likely new gap this phase
      introduces.
- [ ] Report states clearly: is P9 CI/CD fully green? If any fix was needed, which task's code
      and what was wrong.

## Design references
- `.github/workflows/backend-ci.yml`, `.github/workflows/frontend-ci.yml`
- Precedent: `dev-board/code-review/P8-07-cicd-verify/`, `dev-board/code-review/P7-06-cicd-verify/`,
  `dev-board/code-review/P6-10-cicd-verify/`, `dev-board/code-review/SEC-10-container-verify/`
- `dev-board/code-review/P8-08-curated-deps-guard/` — the guard against curated-dependency drift;
  confirm it caught (or should have caught) anything P9 added.

## Constraints / non-goals
- No new features — this task only makes existing P9 code pass the CI gate it will actually
  run under.
