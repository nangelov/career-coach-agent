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

Related: [[project-phase-exit-verification]] (integration tests skip-not-fail on live DB).
