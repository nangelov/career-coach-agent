# Engineer report — P0-11-verify · Revision 1

## Summary

P0 exit-criterion verification. Ran `docker compose up --build -d` from the repo root, built all
three images (backend, worker, frontend), brought up the full 5-service stack, and verified every
P0 exit check **green**:

| # | Check | Result |
|---|-------|--------|
| 1 | `docker compose ps` — 5 services running | **PASS** (db/redis/backend healthy; worker/frontend up) |
| 2 | `GET /health` → 200 + `"status":"ok"` | **PASS** (`{"status":"ok","version":"2.0.0"}`) |
| 3 | `check_pgvector.py` exits 0 | **PASS** (`pgvector OK`) |
| 4 | `check_celery.py` exits 0 | **PASS** (`Celery OK`, worker logged `{'pong': True}`) |
| 5 | `curl http://localhost:3000` → 200 | **PASS** |

**No repo source/config defects were found.** The build and all five services work as authored in
P0-01…P0-10. The only blockers encountered were purely **local-environment** issues (documented and
resolved below); none required changes to tracked files.

## Files changed

- **None tracked.** No source/config files in the repo were modified — the build and stack are
  correct as-is. (`git diff` of tracked files shows only pre-existing P0-06 branch work in
  `docker-compose.yml`, not authored here.)
- `.env` (git-ignored, **not committed**) — populated with the v2-required variables so compose
  interpolation and backend config validation succeed locally:
  `POSTGRES_USER/PASSWORD/DB`, `HF_API_TOKEN`, `JWT_SECRET_KEY`. These are all already documented in
  the committed `.env.example`; the per-developer `.env` is correctly git-ignored.

## Key decisions

- **Treated as verification, not feature work.** Per the task's non-goals, I made the minimal changes
  needed to get checks green and did not add features. Since no repo file was broken, no repo file was
  changed.
- **Ran the `check_*.py` smoke-tests inside the running backend container** (`docker cp` script in →
  `docker compose exec -T backend python /tmp/<script>.py`). This is the deployment-faithful runtime:
  the image has the full dependency tree and the in-network DSNs (`DATABASE_URL → db:5432`,
  `REDIS_URL → redis:6379`) are already injected by compose. (Design ref: locked decision —
  Postgres+Redis only, self-hosted; `dev-board/plan.md` P0 exit criterion.)
- **Also demonstrated the host path** by installing the one missing declared dep (`asyncpg`, from the
  uv cache) into `backend/.venv` and re-running both scripts on the host — both exit 0. The local
  `.venv` is only partially populated (CI-curated, no torch/sqlalchemy/etc. — avoids the ~3GB ML/CUDA
  download), which is why the bare host run initially failed on `ModuleNotFoundError: asyncpg`. This is
  a host artifact, not a repo defect.

## Issues found during verification (and how each was resolved)

1. **Stray host process on port 3000** — a leftover `next-server (v15.5.19)` (pid 402965, cwd
   `frontend/`, running ~1.5h from a prior `next dev`) held host port 3000, so the frontend
   container failed to bind it on first `up` (`address already in use`). Because the frontend
   container was *created* while the port was occupied, its port publish never took even after the
   port freed. **Resolved:** stopped the stray process, then `docker compose up -d --force-recreate
   frontend`. The frontend then published `0.0.0.0:3000->3000/tcp` and returned 200. No repo change —
   this was a developer-machine leftover.
2. **`.env` lacked v2 vars** — the on-disk `.env` still had only v1 keys
   (`HUGGINGFACEHUB_API_TOKEN`, etc.), missing the v2 `POSTGRES_*`, `HF_API_TOKEN`, `JWT_SECRET_KEY`
   that compose interpolation and `app/config.py` require. **Resolved:** populated the (git-ignored)
   `.env` from the committed `.env.example` template. No committed change needed — `.env.example`
   already documents every required key correctly.
3. **Partial local `backend/.venv`** — bare `python backend/scripts/check_pgvector.py` failed on
   missing `asyncpg`. **Resolved:** ran inside the backend container (authoritative), and additionally
   `uv pip install --python backend/.venv/bin/python "asyncpg>=0.29.0"` for a green host run. No repo
   change.

## How to verify

From the repo root, with a populated `.env` (copy `.env.example` → `.env`, fill `POSTGRES_*`,
`HF_API_TOKEN`, `JWT_SECRET_KEY`) and host ports 3000/5432/6379/8000 free:

```bash
docker compose up --build -d
docker compose ps                                   # all 5 services running/healthy
curl -i http://localhost:8000/health                # 200 + {"status":"ok","version":"2.0.0"}
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000   # 200

# Smoke-tests — deployment-faithful (run inside the backend image):
docker cp backend/scripts/check_pgvector.py career-coach-agent-backend-1:/tmp/check_pgvector.py
docker cp backend/scripts/check_celery.py  career-coach-agent-backend-1:/tmp/check_celery.py
docker compose exec -T backend python /tmp/check_pgvector.py     # "pgvector OK", exit 0
docker compose exec -T backend python /tmp/check_celery.py       # "Celery OK",  exit 0
```

### Actual outputs captured

```
$ docker compose ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}"
SERVICE    STATUS                    PORTS
backend    Up 12 minutes (healthy)   0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp
db         Up 12 minutes (healthy)   0.0.0.0:5432->5432/tcp, [::]:5432->5432/tcp
frontend   Up About a minute         0.0.0.0:3000->3000/tcp, [::]:3000->3000/tcp
redis      Up 12 minutes (healthy)   0.0.0.0:6379->6379/tcp, [::]:6379->6379/tcp
worker     Up 12 minutes             8000/tcp

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
content-type: application/json
x-request-id: 19ae4a10-05ed-4691-b42e-215b5866286f
{"status":"ok","version":"2.0.0"}

$ docker compose exec -T backend python /tmp/check_pgvector.py
pgvector OK                                          # exit 0

$ docker compose exec -T backend python /tmp/check_celery.py
Celery OK                                            # exit 0

# worker log confirming the round-trip:
worker-1 | Task tasks.ping[574b3591-...] received
worker-1 | Task tasks.ping[574b3591-...] succeeded in 0.0051s: {'pong': True}

$ curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000
200
```

## Self-check

- [x] Meets acceptance criteria — all 5 P0 exit checks green (ps, /health, pgvector, celery, frontend).
- [x] No secrets committed — only the git-ignored `.env` was populated; `.env.example` already
      documents all keys; no secret hard-coded in any tracked file.
- [x] Router→Service→Agent/Repo layering respected — N/A (no code changes; verification only).
- [x] Tests/lints — out of scope here (CI is P0-09/P0-10). Smoke-tests pass; outputs pasted above.
- [x] No changes to tracked repo files (`git diff` of tracked files shows only pre-existing P0-06
      branch state in `docker-compose.yml`, not authored in this task).

## Notes for reviewers

- The stack is currently **up** on this machine. `docker compose down` (keep volumes) or
  `docker compose down -v` (reset the Postgres init so `01_enable_pgvector.sql` re-runs) to tear down.
- The frontend service has no compose `healthcheck`, so `docker compose ps` shows it as `Up` (not
  `healthy`) — its readiness was verified directly via the `200` from `curl :3000`. If a stricter
  P0 gate is desired, adding a frontend healthcheck would be a small follow-up (flagged, not done —
  out of scope for verification).
