# Engineer report — P2-09-integration-verify · Revision 1

## Summary
Turned the ad-hoc live-DB integration run from FIX-01 into a **documented, reproducible, one-command
workflow** and verified it end-to-end. Ran the full lifecycle myself — bring up the Postgres(+pgvector)
container → migrate → run the whole suite so the live-DB-gated integration tests **execute instead of skip**
→ tear the container down — and fixed the root cause of the one thing that was actually broken along the way:
the documented `make migrate` step could not run standalone because it never loaded the required env.

No app code, tests, migrations, or docker-compose config needed changing — the schema/tests/compose were all
correct. The only fix was in `backend/Makefile` (the repo's canonical dev interface).

### Before / after (proof the gate is real, not coverage rot)
| Run | Command | Result |
|-----|---------|--------|
| Without live DB (baseline) | `make test` | **102 passed, 40 skipped** |
| With container up + migrated | `make test-integration` | **142 passed, 0 skipped** |
| Full self-contained lifecycle | `make test-integration-full` | up db → migrate → **142 passed** → `docker compose down` (clean) |

The 40 skips are the previously-identified live-Postgres gate (`"Postgres not reachable at DATABASE_URL —
integration test skipped"`). With the container up they all execute and pass — the previously-skipped modules
`test_conversation_store`, `test_identity_models`, `test_knowledge_models`, `test_p2_exit_verification`,
`test_structured_models`, `test_vector_search` go from `sssss…` to `.....` in the run output.

## Files changed
- `backend/Makefile` — captured the reproducible live-DB workflow and fixed the broken migrate step:
  - Added `COMPOSE = docker compose -f ../docker-compose.yml` (compose file + `.env` live at repo root; `-f`
    makes the repo root the project dir so root `.env` interpolation works, same as running from the root).
  - Added `LIVE_DB_ENV` shell-prefix variable (**DRY**): loads the root `.env` and exports a localhost async
    DSN. Reused by both live-DB recipes so the derivation lives in exactly one place.
  - Refactored `test-integration` to use `LIVE_DB_ENV` (was an inline copy of the same sourcing/DSN logic).
  - Added `migrate-integration` — applies migrations against the docker-compose Postgres via `LIVE_DB_ENV`.
    This is the **root-cause fix**: plain `make migrate` fails standalone (see Key decisions).
  - Added `test-integration-full` — all-in-one: `up -d --wait db` → `migrate-integration` → `test-integration`
    → `docker compose down`. This IS the documented, reproducible sequence the task asks for.
  - Fixed the misleading comments: `test-integration`'s header pointed at `make migrate` (broken), and
    `migrate`'s intent was ambiguous. Both now state the real env requirement and point at the working targets.
  - Updated `.PHONY`.

## Key decisions
- **Root cause of the one real defect: `make migrate` never loads the env it needs.** `app.config.Settings`
  loads `.env` **relative to the CWD** (`backend/`), which has no `.env`; the credentials `.env` lives at the
  repo root and doesn't even define `DATABASE_URL` (compose builds it from `POSTGRES_*`). So a standalone
  `make migrate` raises `3 validation errors … DATABASE_URL/HF_API_TOKEN/JWT_SECRET_KEY missing`, which means
  the sequence documented in `test-integration`'s comment (`docker compose up -d db && make migrate`) was
  broken. Fixed by adding `migrate-integration`, which sources the root `.env` and builds the localhost DSN
  exactly like `test-integration` already did. Left the general-purpose `migrate` intact (it's valid when the
  vars are exported / a `backend/.env` exists) but corrected its comment.
- **DRY the DSN/env derivation into `LIVE_DB_ENV`.** `test-integration` already had the sourcing+DSN logic
  inline; `migrate-integration` needs the identical logic. One variable, two recipes — no drift.
- **`test-integration-full` is the reproducible artifact.** `up -d --wait db` blocks on the compose
  healthcheck before migrating (no race); `down` tears containers down but **preserves named volumes**
  (`postgres_data`), so the pgvector extension (enabled by the first-init script) and schema survive — a
  re-`up` comes back healthy with no re-migration, which I verified. If pytest fails, make stops before `down`
  so the DB stays up for debugging (documented in the recipe comment).
- **Kept documentation in the Makefile, not the README.** The Makefile is the repo's canonical dev interface
  (CLAUDE.md and FIX-01 both direct contributors to `make` targets); the root `README.md` is still v1-oriented
  (CRA, `pip install -r requirements.txt`). Adding v2 backend-testing docs there would be inconsistent. The
  task explicitly offered "README/Makefile" as alternatives.
- **No CI service container added** — explicitly out of scope per task.md (flagged as a larger follow-up in
  FIX-01's architecture review). This is a local/manual verification workflow.
- **No tests weakened, no skip markers added.** The only change is Makefile tooling.

## How to verify
From a clean checkout with Docker available and a populated root `.env`:
```bash
cd backend && make test-integration-full     # up db → migrate → 142 passed → down
```
Granular / keep-your-stack-running equivalent:
```bash
docker compose up -d --wait db
cd backend && make migrate-integration && make test-integration   # 142 passed, 0 skipped
docker compose down                                                # (or leave up)
```
Baseline without a DB (integration suites skip cleanly, like CI): `cd backend && make test` → 102 / 40 skip.

## Tests (final step — mandatory)
Executed against the real docker-compose Postgres (localhost:5432), not mocks:
- **Baseline** `make test` (no live-DB env): **102 passed, 40 skipped in 6.04s**.
- **`make migrate-integration`**: `alembic upgrade head` succeeds (schema already at head) — exit 0. (Plain
  `make migrate` was confirmed to fail first: `3 validation errors for Settings` — the defect that was fixed.)
- **`make test-integration`**: **142 passed in 12.14s, 0 skipped** — the 6 previously-skipping integration
  modules all execute and pass.
- **`make test-integration-full`** (full lifecycle incl. teardown): `up -d --wait db` (healthy) → migrate →
  **142 passed in 11.88s** → `docker compose down` removed all containers + network cleanly. Verified
  afterward: `docker compose ps` empty, `postgres_data`/`redis_data` volumes preserved, `docker compose up -d`
  restored the stack (db came back **Healthy** with no re-migration — volume persistence confirmed). Left the
  environment as found.
- **Local gate** `make check` (lint + format-check + mypy + test): green — ruff/format/mypy all pass,
  **102 passed, 40 skipped in 6.00s**. No regression from the Makefile change.

## Self-check
- [x] Meets acceptance criteria: reproducible sequence documented (`make test-integration-full` + granular
      targets); previously-skipped tests now execute and pass (102/40 → 142/0); the one genuine failure
      (`make migrate` env-loading) root-caused and fixed; before/after counts documented above as proof.
- [x] No secrets committed; only Makefile tooling touched — Router→Service→Agent/Repo layering untouched.
- [x] Tests/lints pass (pasted above): `make check` green; full live-DB lifecycle green (142/0).
