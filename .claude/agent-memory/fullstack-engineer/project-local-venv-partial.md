---
name: local-venv-partial
description: backend/.venv on this host is partially populated (CI-curated) — missing asyncpg/torch/sqlalchemy etc.; run smoke-tests inside the backend container
metadata:
  type: project
---

The local `backend/.venv` is only partially populated (~115 pkgs: has fastapi/celery/redis, but
NOT asyncpg, sqlalchemy, torch, pgvector, sentence-transformers). It was curated, not a full
`uv sync` — consistent with [[uv-ci-heavy-deps]] (full sync pulls ~3GB ML/CUDA).

**Why:** avoiding the multi-GB ML/CUDA download on the host.

**How to apply:** to run the `backend/scripts/check_*.py` smoke-tests deployment-faithfully, run them
INSIDE the running backend container (`docker cp` the script in, then `docker compose exec -T backend
python /tmp/<script>.py`) — the image has the full dependency tree and the in-network DSNs
(DATABASE_URL → db:5432, REDIS_URL → redis:6379) already set. The scripts read `__file__` at import,
so pipe-via-stdin (`python - < script`) breaks; copy the file in instead. Alternatively, install a
single missing dep into the venv from the uv cache for a host run:
`uv pip install --python backend/.venv/bin/python "asyncpg>=0.29.0"` (instant from ~/.cache/uv).
