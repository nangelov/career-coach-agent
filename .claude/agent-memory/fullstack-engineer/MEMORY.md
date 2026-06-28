# Memory index

- [System Python has no project deps](feedback-system-python-no-deps.md) — fastapi/langchain etc. not installed in the WSL system Python; use py_compile for syntax checks, not import checks
- [pyproject.toml minimum Python version](project-python-version.md) — backend targets Python >=3.11 (LangGraph, asyncio, tomllib all require it)
- [Local Node is 18.19.1](project-node-version.md) — pin Next.js to 15.x (create-next-app@latest installs Next 16 which needs Node >=20.9)
- [mypy --strict gotchas](project-mypy-strict-gotchas.md) — pydantic.mypy plugin, celery-types, starlette Request[Any] needed to pass strict
- [uv CI heavy deps](project-uv-ci-heavy-deps.md) — backend deps pull ~3GB ML/CUDA; curate CI installs + use `uv run --no-sync`
- [Local venv is partial](project-local-venv-partial.md) — backend/.venv missing asyncpg/torch/etc; run check_*.py smoke-tests inside the backend container
