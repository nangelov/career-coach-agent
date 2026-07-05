# Code review — P2-09-integration-verify · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/Makefile:91 | `test-integration-full` starts only `db` (`up -d --wait db`) but tears down with a bare `$(COMPOSE) down`, which stops/removes **every** service in the project (redis, backend, worker, frontend) plus the network — not just what this target started. A dev running the full stack who invokes this target has their whole stack torn down as a side effect. | Optional: scope teardown to `$(COMPOSE) stop db` / `$(COMPOSE) rm -f db`, or document in the recipe comment that `down` is project-wide. Non-blocking — for a self-contained verification target, full teardown is a defensible default. |
| C2 | nit | backend/Makefile:35-36 | `LIVE_DB_ENV` deliberately ends in a trailing `&&`, so it is only valid when a command is appended. Both current call sites do this correctly, but the pattern is fragile for future recipes (a bare `$(LIVE_DB_ENV)` line would be a shell syntax error). | Leave as-is (documented + DRY as intended); just be aware when adding new live-DB recipes that a command must always follow the expansion. |

## Notes
Verified the actual `git diff HEAD -- backend/Makefile` — it matches `engineer.md` precisely. `backend/Makefile` is the only source file touched (other working-tree entries are dev-board/agent-memory bookkeeping, out of scope).

Correctness spot-checks, all pass:
- **`COMPOSE = docker compose -f ../docker-compose.yml`** — correct. `-f ../docker-compose.yml` sets the compose project directory to the repo root, so root-`.env` variable interpolation (`${POSTGRES_USER}` etc.) resolves exactly as running compose from the root. No duplication of the DSN/env logic — the compose var and the `LIVE_DB_ENV` shell var have distinct, non-overlapping jobs.
- **`LIVE_DB_ENV` DRY refactor** — `test-integration` and `migrate-integration` now share one definition; the old inline copy in `test-integration` is gone. The make backslash-newline collapses to a single logical shell line on expansion, so `$(LIVE_DB_ENV) uv run … pytest` runs as one command in one shell. The `$$POSTGRES_*` escaping is correct (make `$$` → shell `$`). Switching the DSN from an inline env-prefix to `export … && …` is functionally equivalent (the subprocess still inherits `DATABASE_URL`). `set -a`/`set +a`/`export`/`.` are all POSIX — portable under make's default `/bin/sh`.
- **`test-integration-full` ordering + failure handling** — recipe lines run in order, each in its own shell, and make aborts on the first non-zero line (none are `-`-prefixed). So: `up -d --wait db` → `migrate-integration` → `test-integration` → `down`. Confirmed the claimed behavior: **if pytest fails, make stops before `down`, leaving the DB up for debugging** (also true if migrate fails). `down` only runs on a fully-green run. `$(MAKE)` recursion propagates child exit codes correctly.
- **`up -d --wait db` is valid** — verified `docker-compose.yml`: the `db` service (`pgvector/pgvector:pg16`, published `5432:5432`) has a `pg_isready` healthcheck, so `--wait` genuinely blocks on health rather than mere start. Service name `db` and `localhost:5432` DSN are correct.
- **`migrate` root-cause fix** — the diagnosis is sound: `app.config.Settings` loads `.env` relative to CWD (`backend/`, which has none), and the root `.env` doesn't define `DATABASE_URL` (compose derives it from `POSTGRES_*`), so a standalone `make migrate` raises the missing-Settings validation error. `migrate-integration` correctly sources root `.env` and builds the localhost async DSN. Leaving general-purpose `migrate` intact with a corrected comment is the right call (still valid when vars are exported / a `backend/.env` exists).
- **`.PHONY`** updated to include `migrate-integration` and `test-integration-full`.

No secrets introduced; no tests weakened or skip-markers added; no app/test/migration/compose changes needed. Acceptance criteria are met and the before/after counts (102/40 → 142/0) are documented. Did not re-run the live lifecycle myself — the engineer's live evidence plus the static verification above are conclusive for a Makefile-only change; both nits are non-blocking style points.
