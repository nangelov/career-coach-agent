# Architecture review — P0-11-verify · engineer revision 1

## Verdict: APPROVED

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Datastores (locked #9, §6/§4) | Postgres + Redis only, self-hosted; **no MongoDB, no managed tier** | `docker-compose.yml` defines exactly `db` (`pgvector/pgvector:pg16`) + `redis` (`redis:7-alpine`), both self-hosted with named volumes. No Mongo, no Neon/Supabase/Upstash. | None. |
| A2 | Async stack (locked / §6.6) | Celery (Redis broker) for async OCR/doc-intel/crawl | `worker` service runs `celery -A app.tasks.celery_app worker`; `check_celery.py` round-trip green (`{'pong': True}`). Same image as backend. | None. |
| A3 | pgvector foundation (locked #3) | `vector` extension available for `vector(4096)` columns at P1 | `01_enable_pgvector.sql` init script wired into the db entrypoint; `check_pgvector.py` confirms `extname='vector'`, exit 0. | None for P0. Dim=4096 columns are a **P1 migration** concern — flagged there, not here (the check verifies the extension, not column dims). |
| A4 | Target structure (§8) | Modular backend (`api/ agents/ llm/ repositories/ ingestion/ memory/ tasks/ guardrails/ services/ pdf/ schemas/`) | All §8 modules present under `backend/app/` plus `config.py` + `main.py`. | None (verification task; structure was gated in P0-01…P0-10). |
| A5 | Frontend path | §8 canonical `frontend/`; v2 coexists at `frontend-v2/` (blessed P0-05) | `frontend` service builds `./frontend-v2`; returns 200. | None — rename owed at **P11 cutover**, not now. See [[project-frontend-path]]. |
| A6 | P0 exit criterion (plan.md) | 5 services healthy; `/health` green; Celery ping returns | All 5 up; `/health` → 200 `{"status":"ok","version":"2.0.0"}`; both smoke-tests exit 0. | None. |
| A7 | Auth/embeddings/LLM seams | SSO-only, in-process embeddings, GLM-5.2 + native tool-calling, no ReAct parser | Out of scope for a P0 integration-verify; no source touched. Not re-litigated here. | None. |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — all modules present; no layering change (verification only, zero tracked-file diff).
- [x] Honors locked decisions — Postgres+Redis only (no Mongo/managed tier), Celery worker, pgvector enabled, frontend-v2 coexistence respected.
- [x] Interfaces-before-implementations — N/A this task (no new code); seams gated in prior P0 tasks.
- [x] Budget posture (free/OSS/self-hosted) — all images are self-hosted OSS (`pgvector/pgvector`, `redis:7-alpine`, locally built backend/worker/frontend); no paid/managed service introduced.

## Notes
- **No tracked-file changes**, consistent with a verification task: the blockers were purely local-environment (stray host port-3000 process, unpopulated git-ignored `.env`, partial host `.venv`) and correctly resolved without touching repo source. `.env.example` already documents every required key — appropriate.
- **Design follow-up (minor, non-blocking):** the `frontend` service has no compose `healthcheck`, so `docker compose ps` reports it `Up` rather than `healthy`; readiness was confirmed via `curl :3000 → 200`. Acceptance criterion wording says "running/healthy" — a frontend healthcheck would make the P0 gate self-asserting. Cheap to add later; log as a follow-up, not a P0 blocker.
- `vector(4096)` column conformance (locked #3) is **not** exercised by `check_pgvector.py` (it only verifies the extension is loaded). This is correct for P0; the dim must be enforced when reviewing the **P1** migrations that create `kb_chunks` / `user_memories`.
