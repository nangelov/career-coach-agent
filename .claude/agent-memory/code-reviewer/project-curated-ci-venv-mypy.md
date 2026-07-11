---
name: project-curated-ci-venv-mypy
description: Reviewing CI dependency/mypy fixes — reproduce in a freshly-built curated venv, not the full dev venv, and verify each fix is load-bearing
metadata:
  type: project
---

CI (`.github/workflows/backend-ci.yml`) runs `mypy`/tests against a **curated** venv
(`uv sync --only-group dev` + a narrow explicit `uv pip install` list), NOT a full
`uv sync`. The full local dev venv has every dep (heavy ML stack: langgraph, docling,
sentence-transformers), so it hides curated-venv-only failures and gives false greens.
This class of bug recurs (FIX-01, FIX-02).

**Why:** intentional "keep CI light" trade-off — heavy/optional libs without stubs are
left curated-absent and resolve to `Any` (`ignore_missing_imports = true`); `strict`'s
`warn_return_any`/`valid-type` then fire in ways the full venv never sees.

**How to apply when reviewing these fixes:**
- Actually rebuild the curated venv per the task's recipe and run `mypy app/ migrations/`.
  Do not trust the full-venv `mypy` result — it is a superset and masks the gap.
- Verify each fix is genuinely load-bearing: `find_spec`-check which libs are present vs
  absent in the curated venv (e.g. `joserfc: True`, `langgraph: False`), so an accidental
  full install isn't silently carrying a "fix".
- Two legit fix shapes: (a) a **light, always-used** runtime dep missing from the curated
  list → add it (same bucket as sqlalchemy/asyncpg/alembic; `joserfc` is transitive via
  authlib). Must be added identically to BOTH the CI step and `backend/Makefile` install
  target (kept in sync per the Makefile header). (b) a **heavy/curated-absent** lib whose
  `Any` resolution breaks a type alias → fix the code (`X: TypeAlias = ...`), never add the
  heavy lib to curated CI or reach for blanket `# type: ignore` / `--no-strict`.
- Runtime floor is Python 3.11 → `typing.TypeAlias`, not PEP 695 `type X = ...` (3.12+).
