# Code review — P2-10-ci-postgres-service · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | .github/workflows/backend-ci.yml:61-65 | `pg_isready` health-cmd has the well-known initdb race: during first-cluster init Postgres briefly accepts unix-socket connections before restarting for TCP, so a step could theoretically connect during that window. In practice the readiness gate plus the intervening checkout/uv/install/lint/format/typecheck steps mean the DB is fully up long before the extension step, so risk is negligible. No change required; noting only so it isn't a surprise if a future reorg moves DB steps earlier. | (optional) if DB steps ever move ahead of the install steps, add a `pg_isready` TCP poll (`-h localhost`) before the first DB command. |

## Notes
Verified by reproducing the exact CI sequence locally against a fresh `pgvector/pgvector:pg16` container with **no init-script mount** (matching a GitHub Actions service container), then tearing it down:

- **Extension enable** — `docker exec -i <container> psql -U postgres -d career_coach_test < migrations/init/01_enable_pgvector.sql` went from no `vector` extension → `vector` present. The `job.services.postgres.id` context is valid GitHub Actions syntax (returns the service container id); the `docker exec -i ... < hostfile` stdin-redirect pattern works. Path `migrations/init/01_enable_pgvector.sql` resolves correctly under `defaults.run.working-directory: backend` (file confirmed at `backend/migrations/init/`).
- **Migration ordering** — `alembic upgrade head` ran 0001→0002→0003→0004 cleanly; 0003 (pgvector tables) succeeds only because the extension step precedes it. Ordering is correct.
- **Full suite** — `pytest` = **142 passed, 0 skipped** (was 102 passed / 40 skipped). Matches the engineer's before/after table exactly.
- **State-leak / flakiness check** (task's explicit concern) — ran `pytest` a **second** consecutive time against the same already-migrated DB (no re-migrate): **142 passed** again, and `users`/`conversations`/`kb_chunks` all had **0 rows** afterward. Tests clean up after themselves; no intra-run leakage. Cross-run leakage is a non-issue since GitHub service containers are ephemeral (created + destroyed per job run).

Other checks that passed:
- **`services.postgres` block** — image, `env` (POSTGRES_USER/PASSWORD/DB), `ports: 5432:5432`, and the `options: >-` folded-scalar health check (`--health-cmd/--health-interval/--health-timeout/--health-retries`) are all valid GitHub Actions service-container syntax.
- **Job-level `env` secrets posture is correct.** `HF_API_TOKEN` / `JWT_SECRET_KEY` are genuine throwaways — required by `app.config.Settings` (which alembic's `env.py` and pytest both instantiate) but unused by these tests; the DB dies with the runner. These should **not** come from repo secrets: fork-PR runs don't receive secrets, so sourcing them from secrets would break CI on external PRs. Hardcoded non-secret placeholders is the right call. `DATABASE_URL` correctly uses `localhost:5432` (the port-mapped host), not the compose `db` hostname.
- **mypy `--strict` regression check** — adding `alembic` to the curated install means mypy now sees alembic's *real* types (previously `Any` via `ignore_missing_imports`). Ran `mypy app/ migrations/` with alembic 1.18.5 installed → **Success: no issues found in 49 source files**. No new strict errors surfaced in `env.py`/migration modules. This was the main risk of the install-list change and it's clean.
- **`alembic` added consistently** to both `.github/workflows/backend-ci.yml`'s curated `uv pip install` list and `backend/Makefile`'s `install` target — the two lists stay in sync (both now end `... pgvector alembic`). Makefile `.PHONY`, `migrate-integration`, and `test-integration-full` additions are internally consistent.
- **Curated-install boundary preserved** — only light pure-Python `alembic` added; no `uv sync` of the heavy ML stack.

Additive, infra-only change; no application-layer or security surface touched. No blockers or majors.
