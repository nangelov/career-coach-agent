# Memory index

- [System Python has no project deps](feedback-system-python-no-deps.md) — fastapi/langchain etc. not installed in the WSL system Python; use py_compile for syntax checks, not import checks
- [pyproject.toml minimum Python version](project-python-version.md) — backend targets Python >=3.11 (LangGraph, asyncio, tomllib all require it)
- [Local Node is 18.19.1](project-node-version.md) — pin Next.js to 15.x (create-next-app@latest installs Next 16 which needs Node >=20.9)
- [mypy --strict gotchas](project-mypy-strict-gotchas.md) — pydantic.mypy plugin, celery-types, starlette Request[Any] needed to pass strict
- [uv CI heavy deps](project-uv-ci-heavy-deps.md) — backend deps pull ~3GB ML/CUDA; curate CI installs + use `uv run --no-sync`
- [Local venv now has DB+tooling deps](project-local-venv-partial.md) — backend/.venv has sqlalchemy/asyncpg/ruff/mypy/pytest; verify on host (localhost:5432); docker backend image is STALE + unmounted
- [Live docker stack](project-live-docker-stack.md) — db/redis/backend containers usually already up; verify infra/DB tasks against real Postgres (localhost:5432, root .env creds)
- [openai SDK omit sentinel](project-openai-sdk-omit-sentinel.md) — openai 2.x uses `omit` not NOT_GIVEN; literal stream=bool for overloads; cast message/tool params; inject MockTransport in tests
- [Frontend Jest/jsdom gotchas](project-frontend-jest-jsdom.md) — jsdom lacks TextEncoder/TextDecoder + scrollIntoView; wrap post-await state updates in act(); no user-event dep
- [pgvector 4096-dim index limit](project-pgvector-4096-index-limit.md) — HNSW caps at 2000/4000 dims; index vector(4096) via binary_quantize bit_hamming + exact-cosine rerank; exclude the functional index from autogenerate
- [Hybrid search RRF](project-hybrid-search-rrf.md) — P2-06 kb_chunks search fuses cosine+ts_rank via RRF with caller weights; EmbeddingClient lazy-loads + injectable encoder seam
- [Cache→durable rehydration must seed cache](project-cache-rehydration-seedback.md) — on cache miss, write the durable-store load back into cache; multi-turn restart test; cap read to cache bound; align field/column lengths
- [Settings loads .env from CWD](project-settings-env-loading.md) — env_file=".env" resolves to backend/ (empty); root .env lacks DATABASE_URL; live-DB make targets must source root .env (LIVE_DB_ENV)
- [Composition-root conventions](project-composition-root.md) — wiring in app/bootstrap.py (thin API layer); AppStateKeys StrEnum; from_settings injection; shared models/_mixins.py; ToolSchema single home; tests/fakes.py
