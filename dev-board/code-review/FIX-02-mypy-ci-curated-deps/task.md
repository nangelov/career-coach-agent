# Task FIX-02-mypy-ci-curated-deps — Fix `uv run --no-sync mypy app/ migrations/` failing in CI's curated venv

- **Phase:** cross-cutting   **Status:** ENG   **Tags:** (B)/(I)

## Scope

`.github/workflows/backend-ci.yml`'s "Type-check (mypy --strict)" step (`uv run --no-sync mypy app/
migrations/`, line 120) fails. It does **not** fail when run against the locally-`uv sync`'d full dev venv
(which has every dependency, including the heavy ML stack) — it only fails against CI's **curated** venv
(the "Install dependencies" step's narrower `uv sync --only-group dev` + explicit light-package list). That
curated/full split is intentional (see the workflow's own comments) but two gaps in the curated list now make
mypy disagree with itself depending on which venv you run it in.

**Root cause, reproduced and diagnosed by the orchestrator** (do not need to re-diagnose — verify and fix):

Built a throwaway venv mirroring CI's exact install steps (`uv sync --only-group dev` +
`uv pip install fastapi pydantic pydantic-settings "celery[redis]" openai sqlalchemy asyncpg aiosqlite
pgvector alembic` — i.e. **not** a full `uv sync`) and ran `mypy app/ migrations/` against it:

```
app/security/tokens.py:109: error: Returning Any from function declared to return "str"  [no-any-return]
app/agents/graph.py:328: error: Variable "app.agents.graph.PlannerNode" is not valid as a type  [valid-type]
app/agents/graph.py:367: error: Variable "app.agents.graph.PlannerNode" is not valid as a type  [valid-type]
app/agents/graph.py:474: error: Variable "app.agents.graph.PlannerNode" is not valid as a type  [valid-type]
app/agents/graph.py:531: error: Variable "app.agents.graph.PlannerNode" is not valid as a type  [valid-type]
Found 5 errors in 2 files (checked 75 source files)
```

1. **`app/security/tokens.py:109`** (`SessionTokenCodec.encode`, P3) — calls `joserfc`'s `jwt.encode(...)` and
   returns its result as `str`. `joserfc` is **not** in the curated CI install list (it's a real runtime
   dependency of `app/security/tokens.py` — used for real JWT signing, not a heavy optional/ML lib like
   torch/docling), so in the curated venv it resolves to `Any` (`ignore_missing_imports = true`), and
   `strict = true`'s `warn_return_any` flags returning that `Any` from a function declared `-> str`. This is a
   **missing-curated-dependency gap**, not a real type bug — `joserfc` belongs in the same "light, always-used
   at runtime" category as `sqlalchemy`/`asyncpg`/`alembic`, which are already curated in.
2. **`app/agents/graph.py:104`** — `PlannerNode = StateNode[AgentState, Any]` (a type alias built on
   `langgraph`'s `StateNode`). `langgraph` is **deliberately excluded** from the curated install (the
   workflow's own comment groups it with `docling` as "third-party libs without published type stubs...
   treated as Any instead of failing the build" — i.e. curated-absent is intentional here, unlike
   `joserfc`). When `StateNode` resolves to `Any` (missing import), `PlannerNode = StateNode[AgentState, Any]`
   is an **un-annotated** module-level assignment whose inferred type is `Any` — and mypy's `valid-type` check
   then rejects *using that variable as a type* (`planner: PlannerNode | None = ...`) because, without an
   explicit `TypeAlias` marker, an `Any`-inferred variable isn't recognized as a type alias. This is a **code
   fix**, not a curated-install fix (adding `langgraph` to curated CI would work but contradicts the documented
   "keep CI light, no ML/heavy-stub-optional libs" intent the comment states — fix the alias declaration
   instead).

## Fix

1. **`app/security/tokens.py`**: add `joserfc` to the curated install list in both
   `.github/workflows/backend-ci.yml` (the "Install dependencies" step) **and** `backend/Makefile`'s `install`
   target (the file's own header comment says: *"Keep this list in sync with the backend/Makefile install
   target (they must produce the same venv)"* — do not update one without the other). Add a one-line comment
   next to it explaining why (mirrors the existing per-package comment style in that step), matching the
   precedent of the other curated-but-not-`uv sync`'d entries.
2. **`app/agents/graph.py`**: make `PlannerNode` an explicit type alias so mypy recognizes it as a type
   regardless of whether `langgraph` resolves to a real type or `Any` — e.g.
   ```python
   from typing import TypeAlias
   ...
   PlannerNode: TypeAlias = StateNode[AgentState, Any]
   ```
   (or the `type PlannerNode = ...` PEP 695 syntax if that's already the codebase's convention — check for
   precedent first). Verify this actually resolves the error in the **curated** venv (not just the full one)
   before reporting done — see verification steps below. If `TypeAlias` doesn't fully resolve it, investigate
   the minimal correct fix (e.g. an explicit `Any` annotation acknowledgment) rather than reaching for "add
   langgraph to curated CI" as a first resort.

## How to verify your fix (do this — don't rely on the full local venv, it will hide these errors)

```bash
cd backend
rm -rf /tmp/ci-venv-verify
UV_PROJECT_ENVIRONMENT=/tmp/ci-venv-verify uv sync --only-group dev
uv pip install --python /tmp/ci-venv-verify/bin/python \
  fastapi pydantic pydantic-settings "celery[redis]" openai \
  sqlalchemy asyncpg aiosqlite pgvector alembic joserfc   # (+ your fix's new package)
/tmp/ci-venv-verify/bin/mypy app/ migrations/
```
This must print `Success: no issues found in N source files` with **zero** errors — this is the faithful
reproduction of what CI's mypy step actually sees (unlike a bare `uv run --no-sync mypy ...` against your
already-`uv sync`'d full dev venv, which will pass regardless of curated-install gaps and give a false
green).

## Acceptance criteria

- [ ] `mypy app/ migrations/` is clean (`Success: no issues found...`) when run against a **freshly built venv
      that mirrors CI's exact curated install steps** (see verification command above) — this is the actual
      bar, not passing against the full local dev venv.
- [ ] `.github/workflows/backend-ci.yml`'s "Install dependencies" step and `backend/Makefile`'s `install`
      target both updated identically (stay in sync, per the Makefile's own header comment).
- [ ] `app/agents/graph.py`'s fix does not weaken the module's actual typing elsewhere (e.g. don't blanket
      `# type: ignore` the whole module — the fix should be scoped to the alias declaration).
- [ ] Full backend test suite (ruff, mypy against the **full** dev venv, pytest) still green — this fix must
      not regress anything that currently passes.
- [ ] `.github/workflows/backend-ci.yml`'s own explanatory comments (the curated-install rationale block, the
      langgraph/docling-as-Any note) are updated if this fix changes what they claim.

## Design references

- `.github/workflows/backend-ci.yml` — the failing step + its curated-install rationale comments.
- `backend/Makefile` — the `install` target that must mirror the CI install step.
- `backend/app/security/tokens.py` (P3-02/P3-03 area) — the `joserfc` usage.
- `backend/app/agents/graph.py` (P4-02) — the `PlannerNode` alias.
- `dev-board/code-review/FIX-01-backend-test-deps/` — the precedent for this exact class of "curated CI venv
  vs. full local venv" dependency-gap bug and how it was fixed/reported previously.

## Constraints / non-goals

- Do NOT add `langgraph` (or any of the heavy/optional ML libs it would drag towards) to the curated CI
  install — that's the documented "keep CI light" trade-off the workflow already made deliberately; fix the
  code instead for that specific error.
- Do NOT silence errors with blanket `# type: ignore` / `--no-strict` flags — fix the actual gap.
- Do NOT change unrelated parts of `graph.py`'s topology/behavior — this is a typing-only fix there.
