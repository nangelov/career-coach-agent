# Architecture review — SEC-03-port-lockdown · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Port lockdown (§7.2, §6.12 / Decision 12) | `docker-compose.yml` publishes **only** the Next.js port; `db`/`redis`/`backend` internal-only | `frontend` keeps `3000:3000`; `ports:` removed from `db`/`redis`/`backend`, replaced with explanatory comments | none — exact match |
| A2 | Opt-in dev exposure (§7.2: "separate opt-in override file, never the default") | override re-adds host ports, must NOT be auto-merged | `docker-compose.dev-ports.yml` (deliberately not `docker-compose.override.yml`); only applies with explicit `-f`; self-documents usage | none |
| A3 | Inter-service calls unchanged (§7.2 diagram) | backend↔db/redis, frontend→backend over private network by service name | `DATABASE_URL`/`REDIS_URL` use `db`/`redis` hostnames; frontend `INTERNAL_API_URL=http://backend:8000` build ARG (matches blessed FIX-05 routing); backend healthcheck curls `localhost:8000` in-container | none |
| A4 | No host-port dependency left silently broken (task AC) | Makefile/CI/docs relying on published host ports updated or unaffected | `backend/Makefile` `test-integration-full` now brings DB up via `COMPOSE_PORTS` (base+override); CI uses its own GH Actions `services: postgres` (`localhost:5432` on runner), unaffected | none |
| A5 | Scope discipline (§7.2 BFF is SEC-04) | do not implement BFF/httpOnly rework; keep the `rewrites()` proxy for now | rewrite proxy untouched; only compose port publishing changed | none — correctly deferred |
| A6 | v1 docs untouched | v1 `localhost:8000` refs describe `uvicorn main:app` (real host bind), not the compose stack | README §Production Mode + CLAUDE frontend note left alone — verified they describe v1 direct run, not compose | correct call |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — infra-only change, no app source or layering touched
- [x] Honors locked decisions — Postgres+Redis self-hosted, no managed tier; frontend as sole entry point; no stack changes
- [x] Interfaces-before-implementations — n/a (compose/Makefile)
- [x] Budget posture respected — no new services, no paid tier

## Notes
- Followers, not blockers:
  - `docs/oauth-setup.md` documents OAuth callback URLs on `http://localhost:8000/...` for local dev. With `:8000` no longer published by default, local OIDC testing now requires either the dev-ports override or (correctly) routing callbacks through the `:3000` frontend origin. This belongs to the **SEC-04/S4 BFF rework** (explicitly out of scope here), where the browser-facing callback surface moves to the Next origin per §7.2/§6.13 — flag it there, not here.
  - `make migrate-integration` run standalone still assumes a host-published `:5432`; it doesn't itself `up` the DB with the override, but that pre-dates this task and `test-integration-full` (the self-contained path) correctly uses `COMPOSE_PORTS`. No action.
- Implementation matches §7.2 verbatim, including the "*(Today all three are published — this must be fixed.)*" remediation note in the design. The design doc's stale "today" caveat could be updated when convenient, but that is doc hygiene, not a conformance gap.
