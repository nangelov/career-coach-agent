# Code review — SEC-03-port-lockdown · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | docker-compose.yml:83 (`worker`) | `worker` has no `ports:` in either the base or override file. Correct (it never published one), but the override's header implies it restores "the internal service ports" — worker legitimately needs none. No change; noting for completeness. | none |
| C2 | nit | backend/Makefile:98 (`test-integration-full` teardown) | Teardown uses `$(COMPOSE) down` (base file only) while bring-up uses `$(COMPOSE_PORTS)`. Verified harmless — same Compose project name (repo dir), so `down` removes the containers regardless of which `-f` set created them. | none (kept for reviewer trail) |

## Notes
Verified against the acceptance criteria:
- **Default = only :3000** — `docker compose -f docker-compose.yml config` publishes exactly `"3000"`; `db`/`redis`/`backend` have no `ports:` entries. Confirmed live (`config -q` exit 0).
- **Inter-service calls unchanged** — `DATABASE_URL`/`REDIS_URL` still use in-network hostnames (`db`, `redis`); backend healthcheck runs `urllib`/`localhost:8000` *inside* the container (no published port needed); frontend reaches backend via the `INTERNAL_API_URL=http://backend:8000` build ARG. None of these depend on a published host port.
- **Opt-in override** — `docker-compose.dev-ports.yml` re-adds `5432/6379/8000`, is deliberately NOT named `docker-compose.override.yml` (so it is not auto-merged), and self-documents the `-f ... -f ...` usage. Confirmed live: with the override, published ports = `8000/5432/6379/3000`; `config -q` exit 0.
- **Makefile host-port dependency** — `test-integration-full` correctly switched to `COMPOSE_PORTS` for `up -d --wait db` (host pytest/alembic hit `localhost:5432`), with DRY `COMPOSE_PORTS` var and updated comments. `test-integration` standalone documents the required override bring-up. CI (`backend-ci.yml`) uses its own GHA `services: postgres`, not this compose file — unaffected.
- **Docs** — the only remaining `localhost:8000`/`5432` refs (README.md, CLAUDE.md) describe the v1 `uvicorn main:app` / CRA dev flow, which genuinely binds those host ports and is out of this task's scope; correctly left alone.

Infra-only change, no application layering or secrets touched. No security concerns — this *reduces* attack surface as intended by §7.2/§6.12. Two nits are informational only and do not warrant changes.
