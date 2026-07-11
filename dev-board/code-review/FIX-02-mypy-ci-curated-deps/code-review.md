# Code review — FIX-02-mypy-ci-curated-deps · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | .github/workflows/backend-ci.yml:99-107 | Rationale comment for `joserfc` is thorough but doesn't note that `joserfc` is a *transitive* dep (via `authlib`), not a direct pyproject entry — so a reader might expect it in `[project].dependencies`. Optional clarity nit only. | Optionally add "(transitive via authlib; not a direct pyproject dep)" to the comment. No change required. |

## Notes
Reproduced the fix against a freshly-built curated venv that mirrors CI's exact install
steps (`uv sync --only-group dev` + the narrow `uv pip install` list, **not** a full
`uv sync`), per the task's verification recipe:

```
Success: no issues found in 75 source files
```

Both root causes are fixed in the correct layer, and I verified each fix is genuinely
load-bearing in the curated venv (not masked by an accidental full install):

- **`joserfc` — missing-curated-dep gap.** Confirmed `joserfc` present and `langgraph`
  absent in the curated venv (`importlib.util.find_spec`: `joserfc: True`,
  `langgraph: False`). `joserfc` is a light, pure-Python JWT lib actually imported by
  `app/security/tokens.py` (`from joserfc import jwt`), transitively available via
  `authlib` in a full sync; curating it in gives mypy real return types so
  `warn_return_any` no longer flags `jwt.encode(...) -> str` at tokens.py:109. Correct
  category call — same "light, always-used" bucket as sqlalchemy/asyncpg/alembic.
  Added identically to both the CI "Install dependencies" step and the `backend/Makefile`
  `install` target (kept in sync per the Makefile's own header note). ✔

- **`PlannerNode` — scoped code fix, not a workaround.** With `langgraph` deliberately
  curated-absent, `StateNode` resolves to `Any`, so the previously un-annotated
  `PlannerNode = StateNode[AgentState, Any]` wasn't recognized as a type alias and mypy's
  `valid-type` rejected its use in annotations (graph.py:328/367/474/531). The fix marks
  it `PlannerNode: TypeAlias = StateNode[AgentState, Any]` — the minimal, correct fix.
  Verified this is what carries the check: `langgraph` is absent from the curated venv, so
  the `TypeAlias` marker is the only thing making mypy treat the `Any`-inferred assignment
  as a type alias. No blanket `# type: ignore`, no `--no-strict`, no `langgraph` added to
  curated CI — honors the documented "keep CI light" trade-off and the task's constraints.
  `TypeAlias` (not PEP 695 `type X =`) is the right choice given the 3.11 runtime floor.

Verification run:
- Curated venv (the actual acceptance bar): `mypy app/ migrations/` → **Success, 0 errors, 75 files**.
- `ruff check app/agents/graph.py` → All checks passed; `ruff format --check` → already formatted (the added `TypeAlias` import is correctly ordered).
- Runtime safety: the RHS `StateNode[AgentState, Any]` was already evaluated at runtime before this change (only the LHS annotation is new, and `from __future__ import annotations` stringizes it), so no behavioral/runtime regression; engineer's full-venv `pytest` (312 passed) is consistent.

All acceptance criteria are met: curated-venv mypy clean; CI step + Makefile updated
identically; graph.py fix scoped to the alias line; full-suite green (engineer-reported,
consistent with the curated result which is the stricter bar); workflow comments updated
accurately (the langgraph/docling-as-Any note remains true — the code now tolerates it).
