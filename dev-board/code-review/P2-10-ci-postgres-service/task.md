# Task P2-10-ci-postgres-service — Postgres(+pgvector) service container in backend CI

- **Phase:** P2 (cross-referenced from FIX-01 and P2-09 follow-ups)   **Status:** ENG   **Tags:** (I)

## Scope
Both `FIX-01-backend-test-deps` and `P2-09-integration-verify` flagged the same standing gap: the ~40
live-Postgres-gated integration tests in `backend/tests/` (`test_conversation_store`, `test_identity_models`,
`test_knowledge_models`, `test_p2_exit_verification`, `test_structured_models`, `test_vector_search`) **skip**
in `.github/workflows/backend-ci.yml` because there's no reachable Postgres in the GitHub Actions runner —
even after `FIX-01` fixed the `pgvector` collection-error bug, these modules still just skip rather than
execute. `P2-09` proved the local workflow (`make test-integration-full`) but deliberately did not touch CI.
This task closes that gap for real: add a Postgres(+pgvector) service container to CI so these tests actually
run on every push/PR, not just when a human remembers to run the local workflow.

### What to do
1. Add a `services:` block to the `backend` job in `.github/workflows/backend-ci.yml` using the same image
   docker-compose uses locally: `pgvector/pgvector:pg16` (see `docker-compose.yml`'s `db` service). Configure
   `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` env, port-map `5432:5432`, and a health check
   (`pg_isready`) so the job waits for it to be ready — GitHub Actions service containers support
   `options: --health-cmd ... --health-interval ... --health-retries ...`.
2. Run migrations against that service before the pytest step (`alembic upgrade head`, or reuse whatever
   `make migrate-integration` does per `P2-09`'s Makefile work — check `backend/Makefile` for the exact
   env-derivation pattern already established there so CI and local stay consistent, DRY where reasonable).
3. Export `DATABASE_URL` (or whatever env var `app.config.Settings` expects) pointing at the CI Postgres
   service host (`localhost` for GitHub Actions service containers, not `db` — that hostname is only valid
   inside the docker-compose network) before the `Test (pytest)` step.
4. Confirm the previously-skipped 40 tests now **execute and pass** in CI, not skip. If anything genuinely
   fails only in the CI environment (timing, permissions, etc.), root-cause and fix it — don't paper over
   with retries/sleeps beyond what's reasonable, don't skip-mark your way past a real failure.
5. Keep the existing curated-install rationale intact (this task is additive — a service container + a
   migration step + an env var — not a full `uv sync`/heavy-ML-stack change).
6. Update the workflow's explanatory comments to reflect the new step (same documentation standard already
   set in this file for the curated install list).

## Acceptance criteria
- [ ] `.github/workflows/backend-ci.yml` has a Postgres(+pgvector) service container wired in.
- [ ] Migrations run against it before tests, and `DATABASE_URL` (or equivalent) is exported correctly for the
      CI environment (`localhost`, not the compose-network hostname).
- [ ] The previously-skipped integration test modules execute and pass in CI (verify via a real CI run if
      possible — e.g. push to a branch and check the Actions run — or clearly document how you validated
      this without a live push, e.g. by exactly reproducing the CI job's steps locally in a clean container/venv).
- [ ] Lint/format/mypy steps are unaffected; total CI time increase is reasonable (service container startup +
      migration, not materially more).
- [ ] `engineer.md` documents before/after CI test counts/behavior for the affected modules.

## Design references
- `dev-board/code-review/FIX-01-backend-test-deps/architecture-review.md` — original follow-up (N1/A5).
- `dev-board/code-review/P2-09-integration-verify/architecture-review.md` — N3, reaffirming this as the next
  step, tracked against P2-exit/P3.
- `docker-compose.yml` — canonical local Postgres(+pgvector) service definition (image, healthcheck, init
  script enabling the `vector` extension).
- `backend/Makefile` — `LIVE_DB_ENV`, `migrate-integration`, `test-integration` targets from P2-09; reuse the
  established DSN-derivation pattern where it makes sense for CI instead of inventing a new one.
- dev-board/plan.md: P0-09 backend CI design intent; P2 exit criteria (persistence/vector search verified).

## Constraints / non-goals
- Do not pull in the full `uv sync` / heavy ML stack (torch/docling) — this task is only about the Postgres
  service + migrations + DATABASE_URL, independent of that curated-install boundary.
- Do not weaken tests or add skip markers to dodge a CI-only failure — fix the root cause.
- Per the agent-handoff skill: running the test suite and fixing root causes of failures is a mandatory final
  step, same as every other task — here that means the CI-equivalent run, validated as described above.
