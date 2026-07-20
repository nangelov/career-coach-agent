# Task P11-05-cicd-verify — P11 CI/CD verification (T)

- **Phase:** P11   **Status:** ENG   **Tags:** (T)

## Scope
Design/plan.md P11 exit: "CI/CD verification — run the full backend + frontend CI command sets
locally (ruff + ruff format --check + mypy + pytest; eslint + tsc + jest — the exact commands in
`.github/workflows/backend-ci.yml` / `frontend-ci.yml`) and confirm both are green before closing
the phase."

1. Read `.github/workflows/backend-ci.yml` and `.github/workflows/frontend-ci.yml`, extract the
   exact command sequence each job runs (including the curated-dependency-list step per
   P8-08-curated-deps-guard — P11-01/P11-02 added `opentelemetry-*` and `sentry-sdk` packages,
   confirm they're correctly curated/allowlisted, not just present in `pyproject.toml`).
2. Run every command locally, exactly as CI does (same working directory, same flags).
3. Fix any drift caused by the P11-01..P11-04 work: new dependencies not yet in the curated list,
   formatting, type errors, lint findings, or test failures.
4. If everything is already green, this task is a short confirmation report — don't invent work.

## Acceptance criteria
- [ ] Backend: `ruff check`, `ruff format --check`, `mypy`, `pytest` all pass locally using the
      exact CI commands.
- [ ] Frontend: `eslint`, `tsc`, `jest` all pass locally using the exact CI commands.
- [ ] Every new backend dependency introduced during P11 (OTel SDK/instrumentation packages,
      `sentry-sdk`) is present in the curated CI dependency list (P8-08 guard) and CI's
      pinned/curated venv build succeeds.
- [ ] `engineer.md` pastes the actual command output/summary for each of the 7 checks above.

## Design references
- dev-board/plan.md — P11 exit criterion; P8-08-curated-deps-guard precedent for the curated-deps
  check; P10-07-cicd-verify precedent for this task's shape.
- `.github/workflows/backend-ci.yml`, `.github/workflows/frontend-ci.yml`

## Constraints / non-goals
- Verification only — do not add new features. Fixes are limited to what's needed to turn CI green.
