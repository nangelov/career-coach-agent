# Architecture review — P0-09-backend-ci · engineer revision 1

## Verdict: APPROVED

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | CI + tooling land at the right paths: workflow under `.github/`, config in `backend/pyproject.toml`, tests in `backend/tests/` | `.github/workflows/backend-ci.yml`, `backend/pyproject.toml`, `backend/tests/{__init__,conftest,test_health}.py`; touched files (`app/main.py`, `scripts/check_pgvector.py`) typing/format only | None — matches §8 layout |
| A2 | plan.md P0, line 27 | "CI: lint/format/type (ruff + mypy backend; eslint/tsc frontend) + test stubs" | Backend half fully delivered: ruff check + ruff format --check + mypy --strict + pytest stub. Frontend CI correctly deferred to P0-10 | None — scope-correct |
| A3 | §3 tech stack (uv, async FastAPI) | uv-managed env; tooling discovers backend config | `setup-uv` + `uv sync --only-group dev`; `working-directory: backend` so ruff/mypy/pytest resolve nested `pyproject.toml`; ASGI app tested in-process via `httpx.ASGITransport` | None — uv posture honored; working-dir choice is correct for config discovery |
| A4 | Layering (Router→Service→Agent/Repo) | CI/test work must not perturb runtime layering | `main.py` change is `dispatch()` type annotations only; no cross-layer leak introduced | None |
| A5 | Locked decisions (Postgres+Redis only; no Mongo) | Test bootstrap must reflect the locked datastore | `conftest.py` seeds `DATABASE_URL=postgresql+asyncpg://…`; no Mongo, no managed-tier references | None — consistent with §4 / locked stack |
| A6 | Budget posture §11 (free/OSS/self-hosted) | CI stays on free/OSS resources, no paid services | GitHub Actions + uv; curated install deliberately excludes the heavy ML/CUDA stack to keep runs cheap; `concurrency` cancels superseded runs | None — strong budget posture; see N1 for the trade-off |
| A7 | Phase fit (foundation-first) | P0 scaffolding only; no premature coupling to P1+ | Stub test hits `/health` only; no agent/LLM/DB integration pulled forward | None |
| A8 | Runtime alignment | type-checker target matches production runtime | mypy `python_version = "3.11"` aligned to `requires-python >=3.11` + Dockerfile `python:3.11-slim` (task had suggested 3.12) | None — see N2; deviation **improves** conformance, blessed |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — CI artifacts in correct paths; layering untouched.
- [x] Honors locked decisions (no ReAct parser; Postgres+Redis only; SSO-only; in-process embeddings) — none in scope; test env references Postgres only, no contradictions introduced.
- [x] Interfaces-before-implementations — N/A for a CI task; no seams added or violated.
- [x] Budget posture respected (free/OSS/self-hosted) — GitHub Actions + uv; ML stack excluded from CI to save minutes.

## Notes

**N1 (design risk — follow-up, not a blocker).** The curated CI install (`uv sync --only-group dev` + a hand-picked light runtime set) combined with `ignore_missing_imports = true` means the strict-mypy gate runs against a *partial* dependency tree: the entire v2 runtime stack (langgraph, sqlalchemy, asyncpg, redis, pgvector, authlib, openai, sentence-transformers, langmem, docling) is currently treated as `Any`. For P0 that is harmless — first-party code doesn't import those yet. But once P1+ modules (`llm/`, `repositories/`, `agents/`) import them, `--strict` will silently pass type-unsafe usage. This is **cheap to unwind** (widen the install, or split deps into a `[project.optional-dependencies] ml`/extras so type-relevant libs are present while CUDA wheels are not), and the engineer already documented it inline in the workflow and in `engineer.md`. Logging as a P1 prerequisite: revisit the CI install before the first PR that imports the heavy stack so the typecheck gate stays meaningful.

**N2 (blessed deviations from the task brief).** Three task-spec suggestions were overridden, and all three are *more* conformant, not less — no action needed:
- mypy `python_version` kept at **3.11** (not 3.12) to match `requires-python >=3.11` and the `python:3.11-slim` Dockerfile — type-checker should track the real runtime.
- `testpaths = ["tests"]` (not `["backend/tests"]`) — correct because rootdir is `backend/`; the brief's value would resolve to `backend/backend/tests`.
- checks run via `working-directory: backend` rather than `backend/`-prefixed commands — required so mypy/pytest discover the nested `pyproject.toml`; semantically equivalent to the brief.

**N3 (no `uv.lock`).** Consistent with P0-02; CI resolves latest-compatible tool versions per run. Engineer verified green on both dependency floors and latest. Acceptable for now; if CI flakiness from tool drift appears later, pinning/locking the dev group is the escape hatch. Not a design concern.

**N4 (frontend path).** Out of scope here — this workflow is path-filtered to `backend/**`, so the `frontend/` vs `frontend-v2/` rename owed at the P11 cutover is untouched. No conflict.
