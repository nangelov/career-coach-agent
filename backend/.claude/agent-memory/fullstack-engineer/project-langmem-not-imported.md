---
name: project-langmem-not-imported
description: langmem is a declared dep but is NOT imported anywhere in app/ — P9 hand-rolled memory extraction; keep it in the curated-deps exclusion allowlist
metadata:
  type: project
---

`langmem` (and its transitive `trustcall`) is declared in `backend/pyproject.toml` but is
**not imported anywhere in `app/`** — `grep -rn langmem app/` returns nothing through P9.

**Why:** P9's teachable-memory implementation deliberately deviated (allowed by the task):
`app/memory/learn.py` hand-rolls extraction+dedup instead of wiring LangMem's
`create_memory_store_manager`, and `app/memory/store.py` conforms to
`langgraph.store.base.BaseStore` (langgraph, which IS in the curated CI venv), not langmem.
Confidence + thumb-down demotion are first-party concepts LangMem doesn't model.

**How to apply:** `langmem` correctly stays in `INTENTIONAL_EXCLUSIONS` in
`scripts/check_curated_deps.py` (reason: "declared but not yet imported anywhere in app/") and
is NOT in the curated `uv pip install` list. A CI-fresh curated venv (no langmem/trustcall)
imports every P9 memory module and runs the full suite green. Only move langmem into the
curated list if/when a module under `app/` actually imports it at module scope. See
[[feedback-ci-curated-deps]].
