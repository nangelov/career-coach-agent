# Task SEC-03-port-lockdown — Compose port lockdown
- **Phase:** SEC   **Status:** ENG   **Tags:** (I)

## Scope
Design §7.2 / §6.12: **the UI is the only entry point; the backend is not a public API.**
`docker-compose.yml` today publishes host ports for `db` (5432), `redis` (6379) and `backend`
(8000) — all three must become internal-only on the default compose file. Only the `frontend`
(Next.js, port 3000) should remain reachable from the host.

- Remove the `ports:` mapping from the `db`, `redis` and `backend` services in
  `docker-compose.yml`. They stay reachable to each other over the default Docker network by
  service name (`db`, `redis`, `backend`) — nothing else changes about how services talk to
  each other (`DATABASE_URL`/`REDIS_URL` already use in-network hostnames; `backend`'s
  healthcheck already runs `curl`/`urllib` *inside* the container against `localhost:8000`, which
  keeps working with no published port).
- Keep the `frontend` service's `3000:3000` mapping — it's the one published port.
- Add a **separate, opt-in override file** (e.g. `docker-compose.dev-ports.yml` or
  `docker-compose.override.example.yml` — pick a name that makes it obviously not
  auto-loaded by plain `docker compose up`, since `docker-compose.override.yml` *is*
  auto-merged by Compose) that re-adds the three host port mappings for local debugging
  (e.g. connecting a DB client to `db:5432` or hitting the backend directly with curl during
  development). Document in a short comment/README note how to use it:
  `docker compose -f docker-compose.yml -f docker-compose.dev-ports.yml up`.
- Update any docs that assume `localhost:8000` / `localhost:5432` / `localhost:6379` reachability
  (check `README.md`, `CLAUDE.md`, `dev-board/*.md` mentions of local ports) to note the new
  default and the opt-in override.
- Sanity-check nothing else in the repo (CI workflows, Makefile targets, test scripts) depends on
  hitting `backend`/`db`/`redis` from the **host** by published port rather than from inside the
  Docker network or via the frontend origin — CI likely runs services differently (its own
  service containers, not this compose file) but double-check `make test-integration*` targets
  mentioned in `dev-board/tasks.md` P2, since those explicitly say `docker compose up -d db`.
  If a Makefile target relies on the host port, it should use the new opt-in override file (or a
  documented alternative) rather than silently breaking.

## Acceptance criteria
- [ ] `docker compose up` (default file only) exposes **only** port 3000 on the host; `db`,
      `redis`, `backend` have no `ports:` entries in `docker-compose.yml`.
- [ ] Inter-service calls (backend→db, backend→redis, worker→db/redis, frontend→backend) still
      work unchanged (internal Docker network, same service hostnames).
- [ ] An opt-in override file exists that restores the three host ports for local debugging, with
      a one-line usage note.
- [ ] Any Makefile/CI/docs step that assumed a published host port (e.g.
      `make test-integration*`, `docker compose up -d db`) still works — either unaffected or
      updated to use the override file.
- [ ] `docker compose config` (or actually bringing the stack up, if feasible in the sandbox)
      confirms the resulting port mappings.

## Design references
- dev-board/app-design-and-features.md §7.2 "Port lockdown" + §6.12 (backend not publicly
  reachable) + the network-posture diagram.
- dev-board/tasks.md — SEC block, item **S5**.

## Constraints / non-goals
- This task does **not** implement the BFF/httpOnly-cookie session rework (that's SEC-04/S4) —
  today's `frontend` rewrite/proxy pattern for `/api/*` can stay as-is for now; only the compose
  port publishing changes here.
- Don't touch the HF Spaces single-container Dockerfile (P11 territory) — this is the local
  `docker-compose.yml` only.
