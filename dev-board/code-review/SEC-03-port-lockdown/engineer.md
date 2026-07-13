# Engineer report — SEC-03-port-lockdown · Revision 1

## Summary
Locked down the local compose stack so the Next.js `frontend` (:3000) is the only
published host port. Removed the `ports:` mappings from `db` (5432), `redis` (6379)
and `backend` (8000) in the default `docker-compose.yml` — they now reach each other
only over the internal Docker network by service name. Added an opt-in override file
(`docker-compose.dev-ports.yml`) that re-publishes the three ports for local
debugging, and updated the one host-port-dependent workflow (`backend/Makefile`
live-DB targets) to use it. Implements design §7.2 "Port lockdown" / §6.12.

## Files changed
- `docker-compose.yml` — removed `ports:` from `db`, `redis`, `backend`; kept
  `frontend`'s `3000:3000`; added a header note + per-service comments documenting
  the lockdown and the override usage.
- `docker-compose.dev-ports.yml` (new) — opt-in override re-adding `5432/6379/8000`.
  Deliberately NOT named `docker-compose.override.yml` (that name auto-merges);
  only applies when passed explicitly with `-f`. Self-documents the usage command.
- `backend/Makefile` — added a `COMPOSE_PORTS` var (base + dev-ports override);
  `test-integration-full` now brings the DB up via `COMPOSE_PORTS` so the
  host-run pytest/alembic can still reach `localhost:5432`; updated comments on
  `test-integration` / the shared `LIVE_DB_ENV` helper to note the port requirement.

## Key decisions
- **Override, not `override.yml`.** Compose auto-merges `docker-compose.override.yml`
  into plain `docker compose up`, which would silently defeat the lockdown. Named it
  `docker-compose.dev-ports.yml` so it is opt-in only (task requirement, §7.2:
  "Local-dev exposure lives in a separate opt-in override file, never the default").
- **Makefile live-DB targets use the override.** `make test-integration` and friends
  run pytest/alembic *on the host* against `localhost:5432`, so they genuinely need
  the DB port published. `test-integration-full` now uses `COMPOSE_PORTS up -d db`;
  otherwise it would break silently. This is the only host-port dependency in the repo.
- **CI unaffected.** `.github/workflows/backend-ci.yml` uses its own GitHub Actions
  `services: postgres` container (its own `5432:5432` on the runner), not this compose
  file — confirmed, no change needed.
- **Inter-service calls unchanged.** `DATABASE_URL`/`REDIS_URL` already use in-network
  hostnames (`db`, `redis`); the `backend` healthcheck curls `localhost:8000` *inside*
  the container. Both keep working with no published port.
- **Left v1 README/CLAUDE `localhost:8000` refs alone.** Those describe running the v1
  app directly via `uvicorn main:app` (which really does bind :8000 on the host) — not
  the compose stack — so they remain accurate and are out of this task's scope.

## How to verify
- Default stack publishes only 3000:
  `docker compose -f docker-compose.yml --env-file .env config | grep published:`
  → only `"3000"`.
- Override restores all four: add `-f docker-compose.dev-ports.yml` → `8000/5432/6379/3000`.
- Both configs valid: `docker compose ... config -q` exits 0 for both.
- Debug locally: `docker compose -f docker-compose.yml -f docker-compose.dev-ports.yml up`.

## Tests (final step — mandatory)
- `docker compose -f docker-compose.yml --env-file .env config -q` → exit 0;
  published ports = `3000` only.
- `docker compose -f docker-compose.yml -f docker-compose.dev-ports.yml --env-file .env config -q`
  → exit 0; published ports = `8000, 5432, 6379, 3000`.
- `cd backend && make test` → **455 passed, 49 skipped in 8.22s**. The 49 skips are the
  live-DB integration suites skipping cleanly (no `localhost:5432` reachable from this
  host run) — the expected, unchanged behavior. No failures.

## Self-check
- [x] Meets acceptance criteria (default = only :3000; override restores 3; inter-service
      calls unchanged; Makefile updated; `docker compose config` confirms mappings).
- [x] No secrets committed; no app layering touched (infra-only change).
- [x] Tests/lints pass (455 passed, 49 skipped; both compose configs valid).
