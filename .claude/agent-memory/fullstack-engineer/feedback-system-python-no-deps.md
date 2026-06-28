---
name: feedback-system-python-no-deps
description: System Python in this WSL env has no project dependencies (fastapi, langchain, etc.) — use py_compile for syntax checks, not import checks
metadata:
  type: feedback
---

Use `python3 -m py_compile <file>` for syntax verification of stub files, not `python3 -c "from ... import ..."`. The WSL system Python does not have project deps installed; import checks will fail on `ModuleNotFoundError` even when the file is perfectly valid.

**Why:** Confirmed on P0-01-backend-skeleton: `from backend.app.main import app` failed with `ModuleNotFoundError: No module named 'fastapi'` despite the file being correct. Had to `pip3 install --break-system-packages fastapi` just to demonstrate import works.

**How to apply:** For all P0–P11 skeleton/stub tasks, use `py_compile` for syntax and `tomllib.loads()` for TOML validation. Reserve actual import tests for tasks that set up a virtualenv or docker environment.
