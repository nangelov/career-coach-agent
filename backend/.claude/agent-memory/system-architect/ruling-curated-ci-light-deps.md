---
name: ruling-curated-ci-light-deps
description: Curated CI venv posture — light always-used runtime deps (incl. authlib, langgraph) get curated in; only heavy ML libs (docling, torch/sentence-transformers) stay absent. Classify by footprint AND tool: pytest executes imports so module-scope deps must be present even if mypy could route around Any.
metadata:
  type: project
---

Backend CI (`.github/workflows/backend-ci.yml` "Install dependencies") uses a **curated** venv:
`uv sync --only-group dev` + an explicit light-package `uv pip install` list — deliberately NOT a full
`uv sync` (which would drag the heavy ML stack: torch via sentence-transformers, docling). This is the
documented free-tier "keep CI light" trade-off.

**Ruling for curated-dependency-gap fixes — classify by BOTH footprint AND which tool needs it:**
- A light, always-used runtime dep (e.g. `joserfc`, `authlib`, `langgraph` — same tier as
  `sqlalchemy`/`asyncpg`/`alembic`/`pgvector`) → **curate it in**.
- Only genuinely-heavy ML/CUDA libs (`docling`, `sentence-transformers`/`torch`) **stay curated-absent**;
  they resolve to `Any` via `ignore_missing_imports`. A mypy error from that `Any` is **fixed in code**
  (e.g. `PlannerNode: TypeAlias = StateNode[...]`), NOT by curating the heavy lib in.
- **mypy vs pytest lens (FIX-03 correction):** `langgraph` was earlier (FIX-02) parked in the
  "stays-absent" tier under the *mypy-only* lens (its `Any` was routed around in code). That was wrong
  once pytest entered the picture: **pytest EXECUTES imports at collection** — no `ignore_missing_imports`
  equivalent — so any dep imported at module scope (langgraph via `app/agents/graph.py`, authlib via
  `app/security/oidc.py`) MUST be installed or the whole suite errors out. langgraph's real transitives
  are light (langchain-core / langgraph-* / pydantic / xxhash — no torch/CUDA), so it belongs in the
  light-curate-in tier. Rule: a module-scope import needed by pytest is curate-in regardless of the mypy
  workaround; only reserve "stays-absent" for heavy libs that NO executed test path imports.
- **Comment-accuracy is part of the fix:** when a lib moves INTO the curated venv, every comment that
  described it as excluded/untyped-`Any` must be corrected in ALL locations — not just the workflow.
  FIX-03 rev1 missed `pyproject.toml [tool.mypy]` and `app/agents/graph.py`'s `TypeAlias` rationale
  (both still named langgraph as absent-and-`Any`). Grep the lib name across `pyproject.toml` +
  workflow + Makefile + the code comment that motivated any `Any`-survival workaround.

**Sync contract:** the CI "Install dependencies" curated list and `backend/Makefile`'s `install` target
must be **byte-identical** (Makefile header: "they must produce the same venv"). Never update one alone.

**Why:** free CI tier; the ML stack is never exercised by lint/type-check/these tests.
**How to apply:** for any FIX-class "curated venv vs full local venv disagreement" task, verify the fix
classified the dep correctly and kept both lists in sync. Precedent: FIX-01, FIX-02.
