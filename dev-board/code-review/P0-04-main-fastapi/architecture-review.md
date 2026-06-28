# Architecture review — P0-04-main-fastapi · engineer revision 1

## Verdict: APPROVED

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | `app/main.py` = "FastAPI app factory, middleware, lifespan" | `create_app()` factory + module-level `app`, CORS/GZip/RequestID middleware, async `lifespan` — exactly the §8 role for this file | none |
| A2 | §8 / config | config read from `app/config.py` pydantic-settings, no hard-coded secrets | imports `settings` from `.config`; CORS origins from `settings.ALLOWED_ORIGINS`, debug from `settings.DEBUG`; no secrets/DSNs in file | none |
| A3 | §4 / §8 layering | Router→Service→Agent/Repo; main owns ASGI shell only, no DB-driver access | only the app shell + a system `/health` route; no service/repo/driver imports; DB+Redis are logging stubs marked `# P2:` | none |
| A4 | locked #9 (Postgres+Redis only, self-hosted) | no DB/Redis drivers wired here (deferred to P2), no managed-tier coupling | lifespan stubs reference Postgres + Redis only, no driver imports, no managed-tier strings | none |
| A5 | phase fit (P0 foundation-first) | minimal app shell, no premature coupling to P3+ (auth) or P4+ (agents/tools) | no auth middleware, no agent/tool/route wiring beyond `/health`; P2/P3 hooks left as comments | none |
| A6 | §9 API surface | feature routers (`/api/...`) belong in `api/` (later phases); only `/health` in scope | single inline `/health` system probe under `tags=["system"]`; feature routers correctly deferred | none — `/health` is a conventional system probe, not a §9 feature route |
| A7 | §6.6 streaming posture | future SSE chat (`/api/chat`) must not be broken by middleware | GZip `minimum_size=1024`, SSE excluded by content type — leaves streaming path intact | none (forward-looking, correct) |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — app shell only, no cross-layer leak
- [x] Honors locked decisions — no ReAct parser; Postgres+Redis only (stubbed for P2); no auth here (P3); no embedding code touched. Config singleton already carries GLM-5.2 / Qwen3-Embedding-8B / guest limits consistently
- [x] Interfaces-before-implementations — N/A for this task (no LLMClient/DocumentParser/repo seams introduced); correctly deferred
- [x] Budget posture respected — nothing paid/managed introduced

## Notes
- **Import path (engineer decision 1 / Notes):** relative `from .config import settings`. §8 does not mandate absolute vs relative; the relative form resolves under both `uvicorn app.main:app` (from `backend/`) and `uvicorn backend.app.main:app` (repo root), so it does not lock the package layout and is cheap to change later. No design objection — package-root canonicalization (`app.*` vs `backend.app.*`) is a code-quality/consistency matter that belongs to the code-reviewer, not a design-gate blocker. If a canonical prefix is later chosen it should be applied package-wide, but that is not required to pass this gate.
- **`/health` inline vs `api/`:** keeping a dependency-free system liveness probe inline in `create_app()` is conventional and does not conflict with §8 reserving `api/` for feature routers. No follow-up needed.
- **Version single-sourcing** via `importlib.metadata.version("career-coach-agent")` with a `"2.0.0"` fallback ties the app version to `pyproject.toml` (P0-02) — good, avoids a second hard-coded version string. No design concern.
- No locked-stack risk areas (pgvector dim 4096, LangMem, mid-stream resume, SSO-only) are touched by this task.
