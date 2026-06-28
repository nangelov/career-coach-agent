# Task P0-11-verify — docker compose up: all 5 services healthy; /health green; ping Celery task returns

- **Phase:** P0   **Status:** ENG   **Tags:** (T)

## Scope

This is the P0 exit-criterion verification task. The engineer must:

1. **Run `docker compose up --build -d`** from the repo root and confirm all 5 services reach a healthy/running state.
2. **Verify `/health`**: `curl http://localhost:8000/health` returns HTTP 200 + `{"status": "ok", ...}`.
3. **Verify pgvector**: run `backend/scripts/check_pgvector.py` — exits 0 with `pgvector OK`.
4. **Verify Celery round-trip**: run `backend/scripts/check_celery.py` — exits 0 with `Celery OK`.
5. **Verify frontend**: `curl -s -o /dev/null -w "%{http_code}" http://localhost:3000` returns 200.
6. **Fix any issues found** during the run (misconfigured env, missing deps, port conflicts, etc.) — patch the relevant files and document what was fixed.
7. Write a **verification report** in `engineer.md` with the exact commands run and their outputs (copy-paste).

If issues are found and fixed, treat this as an integration-fix task: make the minimal changes needed to get all checks green, document everything in `engineer.md`.

## Acceptance criteria

- [ ] `docker compose ps` shows all 5 services (db, redis, backend, worker, frontend) as running/healthy.
- [ ] `GET http://localhost:8000/health` → HTTP 200, body contains `"status": "ok"`.
- [ ] `python backend/scripts/check_pgvector.py` exits 0.
- [ ] `python backend/scripts/check_celery.py` exits 0.
- [ ] `curl http://localhost:3000` returns HTTP 200.
- [ ] All fixes made during verification are committed to the relevant files.
- [ ] `engineer.md` contains actual command outputs (not placeholders).

## Design references

- `dev-board/plan.md` — P0 exit criterion
- `docker-compose.yml` (P0-06)
- `backend/app/main.py` (P0-04)
- `backend/scripts/check_pgvector.py` (P0-07)
- `backend/scripts/check_celery.py` (P0-08)
- `frontend/` (P0-05)

## Constraints / non-goals

- Do not add new features — only fix what is broken to meet the P0 exit criteria.
- If a check cannot be run (e.g. no Docker in the environment), document it clearly and provide the expected output based on the implementation.
- Do not run backend or frontend CI here — that is P0-09/P0-10.
