# Engineer report — P0-04-main-fastapi · Revision 1

## Summary

Replaced the one-line `FastAPI` stub in `backend/app/main.py` with a full app-factory
implementation: a `create_app()` factory, CORS + GZip + request-ID middleware, an async
lifespan with structured DB/Redis startup/shutdown stubs, and a `GET /health` endpoint.
The module-level `app = create_app()` remains the ASGI target.

## Files changed

- `backend/app/main.py` — implemented `create_app()` factory, `lifespan` context manager,
  `RequestIDMiddleware`, `APP_VERSION` resolution, and the `/health` route (was a 5-line stub).

## Key decisions

1. **Relative import `from .config import settings`** — the task text references
   `backend.app.config` / `uvicorn backend.app.main:app`, but the already-merged P0-03 config
   documents and was verified with `from app.config import settings` (package root = `backend/`).
   A package-relative import resolves correctly under *both* invocations
   (`uvicorn app.main:app` from `backend/` and `uvicorn backend.app.main:app` from repo root),
   removing the ambiguity instead of betting on one CWD. (§8: `app/main.py`, `app/config.py`.)

2. **`create_app()` factory + module-level `app`** — matches §8's "FastAPI app factory" note and
   keeps construction explicit/testable; tests can build an isolated instance. uvicorn targets the
   module-level `app`.

3. **CORS origins from `settings.ALLOWED_ORIGINS`** (not hard-coded) — satisfies the acceptance
   criterion and keeps the allowed Next.js origins environment-configurable (config default
   `["http://localhost:3000"]`).

4. **`APP_VERSION` single-sourced via `importlib.metadata.version("career-coach-agent")`** with a
   `"2.0.0"` fallback — prefers the `pyproject.toml` version when the package is installed, avoids
   a second hard-coded version string, and still works for non-installed dev runs (`package = false`
   in `[tool.uv]`).

5. **`RequestIDMiddleware` reuses an inbound `X-Request-ID`** when present (upstream-proxy trace
   continuity) else mints a UUID; the id is stored on `request.state.request_id` for downstream
   handlers/loggers and echoed on the response. Implemented as `BaseHTTPMiddleware` for clarity.

6. **Lifespan = logging stubs only** — startup logs DB-pool init + Redis ping placeholders;
   shutdown logs clean-close placeholders, with `# P2:` markers where real pools land. No DB/Redis
   drivers touched (out of scope; locked decision: Postgres + Redis only, wired in P2).

7. **GZip `minimum_size=1024`** — compresses larger JSON responses; small/SSE responses are
   unaffected (SSE excluded by content type), keeping future streaming chat (§9 `/api/chat`) intact.

## How to verify

```bash
# Syntax (no project deps required)
python3 -m py_compile backend/app/main.py

# Functional — required env vars set so Settings validates
cd backend
HF_API_TOKEN=test DATABASE_URL=postgresql+asyncpg://u:p@localhost/db JWT_SECRET_KEY=secret \
ALLOWED_ORIGINS='["http://localhost:3000","https://example.com"]' \
python3 -c "
from fastapi.testclient import TestClient
from app.main import app, create_app, APP_VERSION
import fastapi
assert isinstance(create_app(), fastapi.FastAPI)
with TestClient(app) as c:
    r = c.get('/health'); print(r.status_code, r.json())
    assert r.json() == {'status':'ok','version':APP_VERSION}
    assert 'X-Request-ID' in r.headers
    pre = c.options('/health', headers={'Origin':'https://example.com','Access-Control-Request-Method':'GET'})
    assert pre.headers['access-control-allow-origin'] == 'https://example.com'
print('OK')
"

# Server start
HF_API_TOKEN=... DATABASE_URL=... JWT_SECRET_KEY=... uvicorn app.main:app   # from backend/
```

Observed results in this environment:
- `GET /health` → `200`, body `{"status":"ok","version":"2.0.0"}`, version equals `APP_VERSION`.
- `X-Request-ID` generated when absent (`6d0388e7…`) and echoed (`abc-123`) when supplied.
- CORS preflight returns `access-control-allow-origin: https://example.com` (sourced from settings).
- Middleware stack: `RequestIDMiddleware`, `GZipMiddleware`, `CORSMiddleware`.
- `create_app()` returns a `FastAPI` instance.

## Self-check

- [x] Meets acceptance criteria (health 200 + version; CORS from settings; lifespan DB+Redis stubs;
  `create_app()` factory returns FastAPI; module-level `app`; imports settings from config).
- [x] No secrets committed; no connection strings hard-coded. Router→Service→Agent/Repo layering
  respected (only the app shell + a system `/health` route added; no DB drivers in any service).
- [x] Tests/lints pass: `py_compile` OK; TestClient functional checks all pass (output above).
  Note: `ruff` is not installed in this environment (`pip` blocked by PEP 668 system policy), so
  lint was verified manually against the configured rules (line-length 100, `UP`/`I`/`E`/`F`);
  `from __future__ import annotations` + PEP 585 builtins used.

## Notes / flags

- Import-path ambiguity between the task text (`backend.app.config`) and the P0-03 convention
  (`app.config`) was resolved with a relative import — see decision 1. If the architect prefers a
  single canonical absolute prefix, that's a one-line change but should be applied consistently
  across the package and documented for later phases.
