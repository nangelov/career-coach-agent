---
name: check-ci-service-container-tasks
description: Checklist for reviewing tasks that add a Postgres(+pgvector) service container to backend CI so live-DB integration tests run
metadata:
  type: project
---

Reviewing a task that wires a Postgres(+pgvector) `services:` block into `.github/workflows/backend-ci.yml` (P2-10 and any future CI service-container work).

**Why:** these gate on GitHub Actions syntax correctness (can't be run here directly) + a hidden mypy regression + test-isolation flakiness. A cached `pgvector/pgvector:pg16` image is usually available, so reproduce the CI flow in a fresh container rather than trusting the report.

**How to apply — concrete checks:**
- **Reproduce the exact CI sequence** in a fresh container with **no init-script mount** (a GHA service container starts before checkout, so it can't mount `migrations/init/`): `docker run -d ... pgvector/pgvector:pg16`, then `docker exec -i <c> psql -U postgres -d career_coach_test < migrations/init/01_enable_pgvector.sql`, then `alembic upgrade head`, then `pytest`. Expect **142 passed, 0 skipped** (was 102 passed / 40 skipped). Use a non-5432 host port to avoid clashing with a local compose DB. Tear the container down after.
- **GHA context/syntax that a static read can't confirm:** `job.services.<name>.id` IS valid (returns the container id); `options: >-` folded scalar with `--health-cmd/--health-interval/--health-timeout/--health-retries` is valid; `docker exec -i ... < hostfile` stdin-redirect works. The init-script path is relative to `defaults.run.working-directory: backend`.
- **mypy `--strict` regression (the main risk):** adding `alembic` to the curated `uv pip install` list means mypy sees alembic's *real* types instead of `Any` (it was covered by `ignore_missing_imports`). Run `uv run --no-sync mypy app/ migrations/` with alembic installed and confirm still "Success" — new real types can surface strict errors in `env.py`/migration modules.
- **Install-list sync:** any dep added to CI's curated list MUST also be added to `backend/Makefile`'s `install` target (they must produce the same venv). Both lists currently end `... pgvector alembic`.
- **Secrets posture:** CI `HF_API_TOKEN`/`JWT_SECRET_KEY` are required by `app.config.Settings` but unused by tests — hardcoded non-secret throwaways are CORRECT, not a finding: fork-PR runs don't receive repo secrets, so sourcing these from secrets would break CI on external PRs. `DATABASE_URL` must use `localhost:5432`, not the compose `db` hostname.
- **Test isolation/flakiness:** run `pytest` twice against the same already-migrated DB (no re-migrate) and confirm 142 passes both times + key tables (users/conversations/kb_chunks) have 0 rows after — proves tests self-clean. Cross-run leak is a non-issue (GHA service containers are ephemeral per run).
- **Migration ordering:** extension-enable step must precede `alembic upgrade head` (migration 0003 = pgvector tables assumes `vector` extension exists). See [[check-alembic-migration-tasks]] for the pgvector-boundary rationale.
- **Known nit (don't over-gate):** `pg_isready` health-cmd has the classic initdb race (temporary socket-only server during first init). Negligible in practice because checkout/uv/install/lint/format/typecheck steps run before any DB step — only worth flagging if DB steps ever move ahead of install.
