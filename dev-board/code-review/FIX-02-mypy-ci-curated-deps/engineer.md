# Engineer report — FIX-02-mypy-ci-curated-deps · Revision 1

## Summary
CI's `mypy app/ migrations/` step failed only against the **curated** venv (`uv sync
--only-group dev` + a narrow light-package list), not the full local dev venv. Two
distinct gaps caused mypy to disagree with itself depending on which venv it ran in:

1. A **missing-curated-dependency gap** — `joserfc` (the real, light JWT lib
   `app/security/tokens.py` signs/verifies session tokens with) was absent from the
   curated list, so it resolved to `Any` and `strict`/`warn_return_any` flagged
   `encode()` returning that `Any` from a `-> str` function.
2. A **code gap** — `PlannerNode = StateNode[AgentState, Any]` was an un-annotated
   module assignment. `langgraph` is deliberately curated-absent, so `StateNode`
   resolves to `Any`; an `Any`-inferred variable isn't recognized as a type alias, so
   mypy's `valid-type` check rejected using `PlannerNode` in annotations.

Fixed each in its correct layer: added `joserfc` to both curated install lists;
marked `PlannerNode` as an explicit `TypeAlias`. Did **not** add `langgraph` to the
curated install (honors the documented "keep CI light" trade-off).

## Files changed
- `backend/app/agents/graph.py` — `PlannerNode: TypeAlias = StateNode[AgentState, Any]`
  (added `TypeAlias` to the `typing` import); doc comment explains why the marker is
  load-bearing under the curated-absent `langgraph`.
- `.github/workflows/backend-ci.yml` — added `joserfc` to the "Install dependencies"
  curated `uv pip install` list, with a rationale comment matching the existing
  per-package comment style.
- `backend/Makefile` — added `joserfc` to the `install` target's curated list (kept in
  sync with the CI step per the workflow's own "must produce the same venv" note).

## Key decisions
- **`joserfc` is curated in, `langgraph` is not** — this mirrors the task's diagnosis and
  the existing precedent (FIX-01): `joserfc` is a light, pure-Python, always-used runtime
  dep in the same category as `sqlalchemy`/`asyncpg`/`alembic`, so it belongs in the
  curated venv where mypy needs its real types. `langgraph` is heavy/optional and stays
  curated-absent by design; its error is a code fix instead.
- **`typing.TypeAlias`, not PEP 695 `type X = ...`** — runtime floor is Python 3.11
  (`requires-python = ">=3.11"`, `mypy python_version = "3.11"`); the `type` statement is
  3.12+. No PEP 695 alias precedent exists in the codebase. `TypeAlias` makes mypy treat
  the assignment as a type alias regardless of whether `StateNode` resolves to a real
  generic or to `Any`, which is exactly what makes it robust across the curated/full split.
- **No comment drift** — the mypy step's "same posture as langgraph/docling" note is still
  accurate (both remain curated-absent/`Any`); the graph.py fix just makes the code
  tolerate that. No workflow comment needed retracting.

## How to verify
```bash
# Faithful reproduction of what CI's mypy step sees (curated venv, NOT a full uv sync):
cd backend
rm -rf /tmp/ci-venv-verify
UV_PROJECT_ENVIRONMENT=/tmp/ci-venv-verify uv sync --only-group dev
uv pip install --python /tmp/ci-venv-verify/bin/python \
  fastapi pydantic pydantic-settings "celery[redis]" openai \
  sqlalchemy asyncpg aiosqlite pgvector alembic joserfc
/tmp/ci-venv-verify/bin/mypy app/ migrations/     # -> Success: no issues found in 75 source files

# Full local gate:
make check   # (ruff check, ruff format --check, mypy, pytest)
```

## Tests (final step — mandatory)
**Curated venv (faithful CI reproduction)** — the actual acceptance bar:
```
=== curated venv mypy ===
Success: no issues found in 75 source files
```

**Full dev venv gate:**
```
ruff check .          -> All checks passed!
ruff format --check . -> 126 files already formatted
mypy app/ migrations/ -> Success: no issues found in 75 source files
pytest -q             -> 312 passed, 43 skipped in 2.74s
```
All green in both venvs. No test failures; no code/test changes were needed beyond the
three files above (the failures were type-check-only, not behavioral).

## Self-check
- [x] Meets acceptance criteria — curated-venv mypy clean; CI step + Makefile updated
      identically; graph.py fix scoped to the alias line (no blanket `# type: ignore`);
      full dev-venv suite still green; no workflow comment claims invalidated.
- [x] No secrets committed; layering untouched (typing-only + CI config).
- [x] Tests/lints pass (output pasted above, both venvs).
