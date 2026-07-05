---
name: feedback-ci-curated-deps
description: Backend CI installs only light deps (fastapi/pydantic/celery[redis]/openai + dev); heavy ML stack is NOT installed
metadata:
  type: feedback
---

Backend CI (`.github/workflows/backend-ci.yml`) does a **curated** install:
`uv sync --only-group dev` + `fastapi pydantic pydantic-settings celery[redis] openai`
— it deliberately does NOT `uv sync` the full project, so the heavy ML stack
(`torch`/`sentence-transformers`, `langgraph`, `langmem`, `docling`) is absent in CI.

**Why:** those libs are huge and slow on the free CI tier; lint/type-check/tests
don't exercise them yet. `mypy`'s `ignore_missing_imports=True` keeps un-installed
libs as `Any` so type-check still passes.
**How to apply:** new backend code (and its tests) may freely import
fastapi/pydantic/openai/`redis` (redis comes via `celery[redis]`), but must NOT
import a heavy ML module at import time or CI's `pytest` will `ModuleNotFoundError`.
If a task needs one, gate it behind a lazy/local import and note that the CI curated
install must be extended.
