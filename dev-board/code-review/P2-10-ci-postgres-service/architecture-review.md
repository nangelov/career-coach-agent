# Architecture review — P2-10-ci-postgres-service · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Datastores — self-hosted, no managed tier (CLAUDE.md locked; §7) | CI DB is a self-hosted OSS Postgres, not a managed tier (Neon/Supabase) | `services.postgres` uses `pgvector/pgvector:pg16` — the *same* OSS image as compose `db`; ephemeral, dies with the runner; no managed provider | None. Faithful to the locked decision. |
| A2 | Free/OSS-first CI posture (§11; P0-09 curated-install rationale) | Additive service + migration step, NOT a creep toward full `uv sync`/heavy-ML stack | Only `alembic` (pure-Python; pulls SQLAlchemy/Mako already present) appended to the curated list; `--no-sync` reuses the curated venv; no torch/docling pulled | None. The curated boundary is preserved and documented in-file (lines 96-100). |
| A3 | pgvector extension bootstrap (P0-07; migration 0001 must NOT create the extension) | Extension enabled outside migrations, mirroring prod entrypoint; migrations assume it pre-exists | "Enable pgvector extension" step feeds the exact checked-out `migrations/init/01_enable_pgvector.sql` to the service via `docker exec`, before `alembic upgrade head`; DDL is not duplicated and not folded into 0001 | None. Best of the three options — see Notes. |
| A4 | DRY / single source of truth | Reuse the established DSN/extension artifacts, don't reinvent | Reuses the same init SQL file and the same image/creds shape; `localhost` DSN mirrors P2-09 `LIVE_DB_ENV` convention; `alembic` kept in sync between CI and `Makefile install` | Pre-existing N2 duplication persists — see Notes (not introduced here). |
| A5 | Closes FIX-01 (N1/A5) + P2-09 (N3) follow-up | The ~40 live-DB-gated tests execute in CI instead of skipping | Reproduced CI-equivalent run: 142 passed, 0 skipped (was 102 passed, 40 skipped); before/after table per module in engineer.md | Gap fully closed. |
| A6 | Migration posture (P2; §7) | Migrations are an explicit, separate step, never auto-run in app lifespan | `alembic upgrade head` is its own step before pytest; matches `make migrate` posture | None. |
| A7 | Layering / target structure (§8) | Infra/CI-only change; no product-code or layering impact | Only `.github/workflows/backend-ci.yml` + `backend/Makefile` touched | None. |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — CI/infra-only, no product surface touched.
- [x] Honors locked decisions — self-hosted Postgres+Redis only, no managed tier (same OSS pgvector image as compose); no Mongo; no ReAct parser / SSO / embeddings surface touched.
- [x] Interfaces-before-implementations — n/a (CI wiring).
- [x] Budget posture respected — free/OSS/self-hosted; GitHub-hosted service container is no-extra-cost; only a light pure-Python dep added.

## Notes
**Q2 (extension bootstrap) — endorsed as the correct call.** Folding `CREATE EXTENSION` into migration 0001
would break the P0-07 invariant (verified: `20260705_0001_baseline.py` lines 15-17 explicitly document the
extension is bootstrapped by the init script, "Migrations assume the extension already exists") and diverge CI
from prod, where the container entrypoint runs the init script. Duplicating the DDL inline in the workflow
would violate DRY. Feeding the *same* checked-out file via `docker exec` (service containers start pre-checkout
so the compose mount is unavailable) preserves both the design boundary and DRY. This is the right seam.

**Follow-ups to track (neither blocks this task):**
- **N1 — Redis is not yet a CI service.** No currently-executing test needs it, so leaving it out is a correct
  YAGNI call now. But when P3 auth/guest-session or Celery live tests land, they will skip-in-CI exactly the way
  the Postgres tests did before this task — a foreseeable repeat of this same gap. Track against P3.
- **N2 — curated-install-list DRY debt persists.** `alembic` was hand-added to *both* `backend-ci.yml` and
  `Makefile install`, keeping them in sync manually. The two lists still drift by hand (this drift caused the
  original FIX-01 pgvector bug). Recommend consolidating into a single `pyproject.toml` dependency group
  referenced by both, next time a CI-touching task is in flight. Cheap; not worth blocking P2-10.

Both follow-ups are cheap-to-add-later and do not require unwinding anything built here — hence APPROVED with
logged follow-ups rather than CHANGES_REQUESTED.
