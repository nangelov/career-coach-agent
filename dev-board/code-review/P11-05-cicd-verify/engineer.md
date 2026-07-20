# Engineer report — P11-05-cicd-verify · Revision 1

## Summary
Ran the exact backend + frontend CI command sequences from `.github/workflows/backend-ci.yml`
and `.github/workflows/frontend-ci.yml` locally. **All 7 checks are green with no drift** — the
P11-01..P11-04 work (OTel core, FastAPI/Celery instrumentation, OTLP exporter, `sentry-sdk`) was
already correctly curated/allowlisted. No source, dependency, or config changes were needed; this
is a confirmation-only pass.

## Files changed
- None. Verification-only task; every check passed as-is.

## Key decisions
- **P11 dependency curation is already correct** (task step 1 / P8-08 guard). The curated-deps guard
  distinguishes the two P11 dependency classes correctly:
  - `opentelemetry-api` + `opentelemetry-sdk` (light, imported at module scope by
    `app/observability/tracing.py` → `app/agents/graph.py` → `app.main`) are in the CURATED
    `uv pip install` list in **both** `backend-ci.yml` (line 137) and `backend/Makefile` (line 58),
    plus declared in `pyproject.toml`.
  - `sentry-sdk` is likewise curated in both (light, real runtime dep).
  - `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-celery`, and
    `opentelemetry-exporter-otlp-proto-http` are lazily imported only when `OTEL_ENABLED` /
    an OTLP endpoint is set, so they are correctly on the `INTENTIONAL_EXCLUSIONS` allowlist in
    `scripts/check_curated_deps.py` — never hit at pytest collection.
- Ran pytest **both** ways: with the default (no `DATABASE_URL`, live-DB suites skip as in a
  service-less run) and against the live docker-compose Postgres (`localhost:5432`, root `.env`
  creds) so the ~80 integration tests that CI's `postgres` service exercises actually execute.

## How to verify
Backend (from `backend/`, exactly as CI):
```
python3 scripts/check_curated_deps.py
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy app/ migrations/
uv run --no-sync pytest              # + live-DB variant via Makefile LIVE_DB_ENV
```
Frontend (from `frontend/`, exactly as CI):
```
npm run lint
npm run type-check
npm test -- --watchAll=false
```

## Tests (final step — mandatory)
Backend (7-of-... CI steps):
- **Curated-dependency drift guard** — `python3 scripts/check_curated_deps.py`
  → `Curated-dependency guard OK: curated CI/Makefile lists cover every runtime dep.` (exit 0)
- **ruff check** — `uv run --no-sync ruff check .` → `All checks passed!` (exit 0)
- **ruff format --check** — `uv run --no-sync ruff format --check .` → `280 files already formatted` (exit 0)
- **mypy --strict** — `uv run --no-sync mypy app/ migrations/` → `Success: no issues found in 165 source files` (exit 0)
- **pytest (no live DB)** — `uv run --no-sync pytest` → `976 passed, 83 skipped in 6.83s` (exit 0)
- **pytest (live Postgres, matches CI service)** — `LIVE_DB_ENV ... uv run --no-sync pytest`
  → `1055 passed, 4 skipped in 12.34s` (exit 0). The 4 residual skips are lazily-imported ML/OCR
  paths (excluded from the curated venv), not regressions.

Frontend (3 CI steps):
- **next lint** — `npm run lint` → `✔ No ESLint warnings or errors` (exit 0)
- **tsc --noEmit** — `npm run type-check` → clean, no output (exit 0)
- **jest** — `npm test -- --watchAll=false` → `Test Suites: 25 passed, 25 total; Tests: 224 passed, 224 total` (exit 0)

No failures; nothing to fix.

## Self-check
- [x] Meets acceptance criteria — backend ruff/format/mypy/pytest green; frontend eslint/tsc/jest green;
      every P11 dependency (OTel SDK/instrumentation, `sentry-sdk`) is curated or allowlisted and the
      curated-deps guard passes.
- [x] No secrets committed; no layering changes (verification-only).
- [x] Tests/lints pass (output pasted above).

## Notes
- Local Node is v18.19.1 vs CI's Node 22; frontend lint/type-check/jest still pass identically.
- `next lint` prints a deprecation notice ("removed in Next.js 16") but exits 0 — informational, not a
  failure. Out of scope for this verification task.
