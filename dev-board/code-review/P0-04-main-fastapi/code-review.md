# Code review — P0-04-main-fastapi · engineer revision 1

## Verdict: APPROVED

## Findings

| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | backend/app/main.py:41-55,109 | `RequestIDMiddleware` is a `BaseHTTPMiddleware` and is added outermost, so it wraps **every** response. `BaseHTTPMiddleware` is documented to buffer/consume the response body and is a known breaker of SSE/streaming — yet streaming chat (`/api/chat`, §9) is a core v2 feature. No streaming endpoint exists yet, so nothing is broken today, but this will bite when SSE lands. | Before the streaming phase, reimplement request-id as a pure ASGI middleware (or set it via a dependency) instead of `BaseHTTPMiddleware`. Flagging now so it is not forgotten. |
| C2 | nit | backend/app/main.py:99-109 | Middleware add order is CORS, GZip, RequestID. Starlette prepends, so CORS ends up **innermost**. Convention is to register CORS last (outermost) so CORS headers reliably attach to error responses and preflights. Preflight works in the happy path (verified), so this is cosmetic/defensive only. | Optionally add `CORSMiddleware` last so it is the outermost layer. |
| C3 | minor | backend/app/main.py (root cause: backend/app/config.py) | AC#5 ("`uvicorn backend.app.main:app` starts without errors") fails **from the repo root**: config's `env_file=".env"` (CWD-relative) picks up the leftover **v1** repo-root `.env` containing `HUGGINGFACEHUB_API_TOKEN`, which trips pydantic-settings `extra_forbidden`. The `backend.app.main` module path itself resolves fine (PEP 420 namespace package — verified). This is a config/P0-03 + stray-`.env` concern, not a defect in `main.py`. | Track for config/P0-03: make `env_file` point at `backend/.env` (or set `extra="ignore"`), and/or remove the v1 root `.env`. Not gating this task. |

## Notes

- Acceptance criteria verified functionally from `backend/` (the documented CWD) with required env vars set:
  - `GET /health` → 200, body `{"status":"ok","version":"2.0.0"}`, version == `APP_VERSION`. ✔
  - `X-Request-ID` minted when absent and echoed (`abc-123`) when supplied. ✔
  - CORS preflight returns `access-control-allow-origin: https://example.com`, sourced from `settings.ALLOWED_ORIGINS` (not hard-coded). ✔
  - `create_app()` returns a `FastAPI` instance; module-level `app` present. ✔
  - `python3 -m py_compile backend/app/main.py` OK. ✔
- Security: no secrets/connection strings hard-coded; `settings` is the single source. `allow_credentials=True` is paired with an explicit origin list (not `*`), so no credentialed-wildcard CORS hole. No arbitrary-execution surface. ✔
- `APP_VERSION` single-sourcing via `importlib.metadata.version("career-coach-agent")` with a `"2.0.0"` fallback is sound (pyproject `name = "career-coach-agent"` confirmed; `package = false` dev runs hit the fallback).
- Lifespan correctly structures startup→yield→shutdown with `# P2:` stub markers for Postgres/Redis — matches the task's stub-only scope.
- `ruff` is not installed in this environment, so lint was not machine-run; code is consistent with the configured style (`from __future__ import annotations`, PEP 585 builtins, line length within 100).
- Design-conformance (layering, §8 placement) is the system-architect's call — not gated here.
