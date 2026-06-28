# Architecture review — P0-01-backend-skeleton · engineer revision 1

## Verdict: APPROVED

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure — sub-packages | `app/` contains api, agents, llm, tools, ingestion, memory, tasks, guardrails, services, repositories, pdf, schemas | All 12 present, each with `__init__.py` | None |
| A2 | §8 — app factory | `app/main.py` = FastAPI app factory (middleware/lifespan land later) | `app = FastAPI(title=..., version="2.0.0")`, importable | None |
| A3 | §8 — config | `app/config.py` = pydantic-settings | Stub comment deferring to P0-03-config | None — correctly deferred per task non-goal |
| A4 | §8 — migrations | `migrations/` for alembic (postgres) | `migrations/.gitkeep` present | None |
| A5 | §8 — tests | `tests/` | `tests/__init__.py` present | None |
| A6 | §8 — packaging | `pyproject.toml` (uv/poetry; replaces requirements.txt) | Valid TOML, `[project]` name + `requires-python=">=3.11"`, empty deps | None — deps deferred to P0-02 per task |
| A7 | §8 — backend Dockerfile | `backend/Dockerfile` | Single-comment stub deferring to P0 infra task | None — correctly deferred |
| A8 | Phase fit (P0 scaffolding) | Skeleton only, no logic, no premature coupling to later phases | Empty packages + stubs; no business logic | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — directory seams for all layers exist; no cross-layer code yet to violate it.
- [x] Honors locked decisions — N/A at skeleton stage; nothing premature. No ReAct parser introduced, no datastore/auth/embedding code that could contradict the locked stack. Naming reserves the correct seams (`llm/`, `repositories/`, `guardrails/`, `memory/`, `tasks/`).
- [x] Interfaces-before-implementations — seam directories (`llm/`, `repositories/`, `guardrails/`, `ingestion/`) exist for future `LLMClient`/`DocumentParser`/repo interfaces; none implemented yet (correct for P0).
- [x] Budget posture respected — no paid deps; `dependencies = []`.

## Notes
- `requires-python = ">=3.11"` is a sound floor (LangGraph, `tomllib`, async typing). No design ref pins a minimum, so this is an acceptable engineer call; revisit only if a later dep needs a different floor. Logged as a follow-up, not a gate.
- Hygiene (code-reviewer's domain, not a design gate): committed `backend/**/__pycache__/*.pyc` artifacts are tracked under the untracked `backend/` tree — a `.gitignore` for `__pycache__/`/`*.pyc` should land with the P0 infra task so build artifacts don't get committed. Non-blocking for this skeleton.
- §8 shows named files inside `api/`, `agents/`, `llm/`, `repositories/` (e.g. `chat.py`, `graph.py`, `client.py`, `postgres.py`). These are intentionally out of scope here (empty packages only, per the task) and will be filled by their respective phase tasks — correct foundation-first sequencing.
