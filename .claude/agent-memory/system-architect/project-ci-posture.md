---
name: project-ci-posture
description: Blessed backend-CI design posture — live-DB integration deferred out of CI (skip-not-fail), curated light install, DRY follow-up on the duplicated install list
metadata:
  type: project
---

Backend CI (`.github/workflows/backend-ci.yml`) design posture, ratified across P0-09 and FIX-01.

**Fact / ruling:**
- Live-Postgres/Redis **integration tests are intentionally deferred out of CI** — P0-09 task.md non-goals
  explicitly say "No integration tests against a live DB/Redis … Do not run docker compose in CI." Tests that
  need a live DB use a **skip-not-fail** connection probe ("Postgres not reachable at DATABASE_URL — skipped").
  Integration coverage runs via `backend/Makefile` `test-integration` against docker-compose. This is
  **expected-by-design**, not a coverage-rot gap — do not re-litigate it as a defect per task.
- CI uses a **curated light install** (dev group + hand-picked light runtime libs), deliberately excluding the
  heavy ML/CUDA stack (torch/sentence-transformers/docling). Any *light, required-at-import* lib (sqlalchemy,
  asyncpg, aiosqlite, **pgvector** client) must be listed explicitly or the suite errors at collection
  (this was the FIX-01 bug: pgvector missing → 8 modules failed collection in CI).

**Why:** §11 budget = free/OSS/self-hosted; keep CI minutes cheap. NOTE the nuance: GitHub-hosted runners
provide Postgres `services:` containers **at no extra cost**, so adding live-DB CI coverage is *not*
budget-blocked — it's deferred on **scope** grounds (needs pgvector image + `alembic upgrade head` +
DATABASE_URL). Don't let "free-tier posture" be used to argue it's impossible; it's a deliberate decision.

**How to apply:**
- If a task classifies live-DB-skip tests as expected-by-design and flags CI-service-container as a follow-up
  (not implemented) → that is the correct scope call for a fix/minimal task; APPROVE.
- Open **DRY follow-up (N2)**: the curated install list is duplicated in `backend-ci.yml` AND `Makefile install`
  and drifting between them caused FIX-01. Fix = a single `[dependency-groups]` `ci-runtime` group in
  `backend/pyproject.toml` referenced by both. Cheap; flag it if a future CI-touching task doesn't consolidate.
- Real (accepted) risk: P2 persistence / pgvector / migration paths are unguarded on PRs until a CI Postgres
  service lands. Recommend tracking that follow-up against P2-exit/P3, not budget.
- **P2-09 (APPROVED):** blessed the local live-DB lifecycle target `backend/Makefile test-integration-full`
  (`compose up -d --wait db → migrate-integration → test-integration → down`; `LIVE_DB_ENV` DRYs the
  root-.env sourcing + localhost DSN). Makefile-only scope for a (T) verify task is correct — docs stay in the
  Makefile (v1 root README untouched), no CI service container (still the standing follow-up). Nuance to flag,
  not block: `docker compose down` (no `-v`) preserves `postgres_data`, so the pgvector init script
  (`migrations/init/01_enable_pgvector.sql`, runs only on first/empty-volume init) does NOT re-run on re-`up`;
  a *pgvector-setup/init-script* change needs `down -v` to re-verify from empty. Schema/migration changes are
  fine (alembic upgrade head against the persisted volume).

- **P2-10 (APPROVED):** the standing CI-service-container follow-up is now **CLOSED** — `backend-ci.yml`
  gained a `pgvector/pgvector:pg16` `services.postgres` (same OSS image as compose `db`, ephemeral, no managed
  tier) + `alembic upgrade head` step; the ~40 live-DB tests execute (142 passed, 0 skipped) instead of
  skipping. Blessed patterns: (a) enable the extension by feeding the **exact checked-out
  `migrations/init/01_enable_pgvector.sql`** to the service via `docker exec` — NOT duplicating the DDL and NOT
  folding CREATE EXTENSION into migration 0001 (preserves P0-07 invariant that migrations assume the extension
  pre-exists, mirroring prod entrypoint); (b) `alembic` is a light/pure-Python add to the curated list — does
  NOT breach the no-heavy-ML boundary; `--no-sync` keeps the curated venv. Two NEW follow-ups to track (neither
  a blocker): (1) **Redis is still not a CI service** — when P3 auth/guest-session or Celery live tests land
  they will skip-in-CI the same way, a foreseeable repeat of this gap; (2) the curated-install-list **DRY
  follow-up (N2) is still open** — `alembic` was added to both `backend-ci.yml` and `Makefile install` by hand;
  the two lists still drift-by-hand, consolidate into a `pyproject.toml` group when a future CI task touches it.

Related: [[project-phase-exit-verification]] (integration tests skip-not-fail on live DB).
