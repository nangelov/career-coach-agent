# Code review — P0-02-pyproject-uv · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | requirements.txt | The "keep temporarily" note lives only in `engineer.md`, not in the repo itself. Acceptance allows a note, but a future contributor reading the tree won't see why two dependency files coexist. | Optional: add a one-line comment at the top of root `requirements.txt` (e.g. `# v1-only — delete when the v1 root Dockerfile/app.py are removed`) so the rationale survives outside the handoff folder. |
| C2 | nit | backend/pyproject.toml:26 | `langmem>=0.0.1` is an effectively-unpinned floor (any 0.0.x). Acceptable under the "min bounds / unpinned" constraint, but offers no real lower guarantee. | None required; revisit the floor once `uv lock` pins a concrete working version. |
| C3 | nit | backend/pyproject.toml:21,42 | `httpx` is declared in both runtime and dev groups. Harmless (uv resolves once) and self-documents test-client use, as the engineer notes. | None required. |

## Notes
- TOML validity confirmed: `tomllib.load` succeeds; 20 runtime deps + 5 dev deps.
- All required sections present and correct: `[project]` (`requires-python = ">=3.11"`), `[tool.ruff]` (`line-length = 100`, `target-version = "py311"`), `[tool.ruff.lint]` (`select = ["E","F","I","UP"]`), `[tool.mypy]` (`strict = true`, `python_version = "3.11"`), `[tool.pytest.ini_options]` (`asyncio_mode = "auto"`, `testpaths = ["tests"]`). Engineer's verify snippet reproduced clean.
- Dependency set cross-checked against `app-design-and-features.md` §2 tech stack and the locked decisions: fastapi/uvicorn, pydantic(+settings), sqlalchemy/alembic/asyncpg/pgvector/redis, authlib/httpx, openai (HF OpenAI-compatible), sentence-transformers (in-process embeddings), langgraph + langmem, celery[redis], docling + Pillow, reportlab, google-search-results. No MongoDB, no managed-tier, no `run_python_code`/REPL dependency — all locked exclusions honored.
- Moving `select` to `[tool.ruff.lint]` (engineer Key Decision #2) is the correct current ruff idiom; the task's placement under `[tool.ruff]` is the deprecated form. Good call, no deprecation warning will be emitted.
- `[tool.uv] package = false` is appropriate for an application; with it set, the absence of a `[build-system]` table is fine (uv won't attempt to build the project).
- Dev deps correctly in `[dependency-groups]` (PEP 735 / uv convention), not `[project.optional-dependencies]`.
- Config-only task: no Python logic, no secrets, no untrusted-input or auth surface to review.
- `requirements.txt` retention is a sound, design-aligned call (plan: stand up `backend/` alongside v1, delete v1 after parity) and explicitly permitted by the acceptance criteria. Design-conformance of the overall file is the system-architect's lane; nothing here blocks on correctness/security/quality.
