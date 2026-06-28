---
name: project-python-version
description: Backend targets Python >=3.11 — set in pyproject.toml and all tooling
metadata:
  type: project
---

The v2 backend `pyproject.toml` uses `requires-python = ">=3.11"`.

**Why:** LangGraph, modern asyncio patterns (`TaskGroup`), `tomllib` in stdlib, and type-hint features (e.g. `X | Y` union syntax) all land cleanly on 3.11+. This was the floor chosen on P0-01 and should remain consistent across all subsequent tasks.

**How to apply:** When adding tooling configs (mypy, ruff, docker base image), always reference Python 3.11 as the minimum. Do not use 3.10-or-below-only patterns.
