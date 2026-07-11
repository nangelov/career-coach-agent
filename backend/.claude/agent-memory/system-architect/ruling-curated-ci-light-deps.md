---
name: ruling-curated-ci-light-deps
description: Curated CI venv posture — light always-used runtime deps get curated in; heavy/optional libs (langgraph, docling, torch/sentence-transformers) stay curated-absent and mypy errors on them are code-fixed, not routed around
metadata:
  type: project
---

Backend CI (`.github/workflows/backend-ci.yml` "Install dependencies") uses a **curated** venv:
`uv sync --only-group dev` + an explicit light-package `uv pip install` list — deliberately NOT a full
`uv sync` (which would drag the heavy ML stack: torch via sentence-transformers, docling). This is the
documented free-tier "keep CI light" trade-off.

**Ruling for curated-dependency-gap fixes:**
- A light, pure-Python, always-used runtime dep (e.g. `joserfc` = Authlib's JOSE, in the same tier as
  `sqlalchemy`/`asyncpg`/`alembic`/`pgvector`) → **curate it in** so mypy sees its real types.
- A heavy/optional lib (`langgraph`, `docling`, sentence-transformers/torch) → **stays curated-absent**;
  it resolves to `Any` via `ignore_missing_imports`. A mypy error arising from that `Any` must be
  **fixed in code** (e.g. `PlannerNode: TypeAlias = StateNode[...]` to survive `StateNode → Any`), NOT
  by adding the heavy lib to curated CI.

**Sync contract:** the CI "Install dependencies" curated list and `backend/Makefile`'s `install` target
must be **byte-identical** (Makefile header: "they must produce the same venv"). Never update one alone.

**Why:** free CI tier; the ML stack is never exercised by lint/type-check/these tests.
**How to apply:** for any FIX-class "curated venv vs full local venv disagreement" task, verify the fix
classified the dep correctly and kept both lists in sync. Precedent: FIX-01, FIX-02.
