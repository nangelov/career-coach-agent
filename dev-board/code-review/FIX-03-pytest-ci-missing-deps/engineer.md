# Engineer report — FIX-03-pytest-ci-missing-deps · Revision 2

## Summary
The GitHub Actions `backend-ci` `Test (pytest)` step failed with 27 collection errors
(exit 2) because two real, `pyproject.toml`-declared runtime deps — `authlib` (OIDC/PKCE
client, imported at module scope via `app/security/oidc.py` → `app.main`) and `langgraph`
(multi-agent graph lib, imported via `app/agents/graph.py` → `app.agents`) — were missing
from the **curated** CI/Makefile install list (the narrower `uv sync --only-group dev` +
explicit light-package `uv pip install`, used instead of a full `uv sync` to avoid the
heavy ML stack). `mypy` didn't catch this because `ignore_missing_imports=true` types a
missing import as `Any`, but `pytest` genuinely executes the imports at collection time.

Fix: added `authlib langgraph` to the curated install list in both the workflow and the
Makefile (both are light — no torch/CUDA/ML transitives), and corrected the stale comment
that grouped `langgraph` with `docling` as excluded-and-`Any`. No application code changed.

## Files changed
- `.github/workflows/backend-ci.yml` — added `authlib langgraph` to the "Install
  dependencies" curated `uv pip install`; extended the install-step comment block to
  document why both are curated in (light, always-imported at module scope); rewrote the
  mypy-step comment so `langgraph` is no longer described as excluded-and-`Any` (only
  docling / sentence-transformers / torch remain excluded and untyped).
- `backend/Makefile` — added `authlib langgraph` to the `install` target's curated
  `uv pip install`, kept identical to the workflow (per the file's own sync contract).
- `.claude/agent-memory/fullstack-engineer/feedback-ci-curated-deps.md` — refreshed my
  own memory: current curated list, the pytest-executes-imports (unlike mypy) gotcha, and
  the rule to re-verify all four tools against a fresh curated venv after any list change.

## Key decisions
- **Curate the deps in rather than skip/xfail or lazy-import** — per task constraints and
  design ref `FIX-01`/`FIX-02` precedent: these are real always-used runtime deps imported
  at module scope; the correct fix is installing them, matching how `joserfc`/`sqlalchemy`
  were handled. Verified neither drags in torch/CUDA/ML (langgraph pulls only
  langchain-core / langgraph-checkpoint / langgraph-prebuilt / langgraph-sdk / pydantic /
  xxhash), so the documented "keep CI light" intent (exclude sentence-transformers / torch
  / docling) is preserved.
- **Kept both lists byte-identical** — the Makefile header and the workflow comment both
  state they must produce the same venv; divergence is exactly the class of bug FIX-01–03
  keep hitting.
- **Did NOT touch `app/security/oidc.py` or `app/agents/graph.py`** — per non-goals; the
  code correctly declares these as deps, only the curated install list was stale.

## How to verify
```bash
cd backend
rm -rf /tmp/ci-venv-verify
UV_PROJECT_ENVIRONMENT=/tmp/ci-venv-verify uv sync --only-group dev
uv pip install --python /tmp/ci-venv-verify/bin/python \
  fastapi pydantic pydantic-settings "celery[redis]" openai \
  sqlalchemy asyncpg aiosqlite pgvector alembic joserfc authlib langgraph
/tmp/ci-venv-verify/bin/ruff check .
/tmp/ci-venv-verify/bin/ruff format --check .
/tmp/ci-venv-verify/bin/mypy app/ migrations/
# live-DB parity:
docker compose -f ../docker-compose.yml up -d --wait db
set -a && . ../.env && set +a
export DATABASE_URL="postgresql+asyncpg://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:5432/$POSTGRES_DB"
export HF_API_TOKEN=ci-not-a-real-token JWT_SECRET_KEY=ci-not-a-real-secret
/tmp/ci-venv-verify/bin/python -m alembic upgrade head
/tmp/ci-venv-verify/bin/python -m pytest
docker compose -f ../docker-compose.yml down
```

## Tests (final step — mandatory)
All runs green; **zero collection errors / zero ModuleNotFoundError**.

Curated CI-parity venv (`/tmp/ci-venv-verify`), built exactly as CI does:
- `uv pip list` confirms `authlib 1.7.2`, `langgraph 1.2.9` present; **no** torch /
  sentence-transformers / docling pulled in.
- `ruff check .` → `All checks passed!`
- `ruff format --check .` → `126 files already formatted`
- `mypy app/ migrations/` → `Success: no issues found in 75 source files`
- `pytest` **with live migrated Postgres** → `355 passed in 6.93s`
- `pytest` **without a live DB** → `312 passed, 43 skipped in 2.77s`

Full local dev venv (`uv run --no-sync pytest`, no DB up) → `312 passed, 43 skipped in 2.63s`.

No failures at any step; nothing to root-cause.

## Self-check
- [x] Meets acceptance criteria (curated-venv pytest: 0 collection errors; both install
      lists updated identically; **all three** stale langgraph comments corrected; suite green
      on full + curated venv, with and without live DB; ruff/format/mypy clean in curated venv)
- [x] No secrets committed; no app code logic touched (install-list + comments + memory only) —
      layering untouched
- [x] Tests/lints pass (results pasted above / re-verified in revision 2)

---

## Response to review (revision 2)

`code-review.md` = APPROVED (no action). `architecture-review.md` = CHANGES_REQUESTED with the
substantive fix fully approved; the only gap was an incomplete acceptance criterion #3 — two
comments still falsely framed `langgraph` as excluded/untyped-as-`Any`. Both are now corrected.

- **A5a — `backend/pyproject.toml` `[tool.mypy]` L70-71 (canonical mypy-posture doc).**
  Rewrote the `ignore_missing_imports` comment. It no longer names `langgraph` as a
  "treated as Any" example; it now lists only the deliberately-excluded heavy ML libs
  (`docling`, `sentence-transformers`, `torch`) and explicitly notes langgraph IS installed
  in CI so its real types apply.

- **A5b — `backend/app/agents/graph.py` L102-108 (`PlannerNode: TypeAlias` rationale).**
  Corrected the inverted premise. The comment no longer asserts "langgraph is deliberately
  absent from CI's curated venv, so `StateNode` resolves to `Any` there." It now states the
  truthful reason the explicit `TypeAlias` marker is kept: `StateNode` comes from langgraph's
  **private** `langgraph.graph._node` module, and the marker declares `PlannerNode`
  unambiguously as a type alias so mypy accepts it in annotations regardless of how that
  private symbol is inferred. Per the reviewer's follow-up note, I kept the marker rather than
  removing it (mypy passes either way; it is harmless and makes the alias intent explicit) —
  scoped this to a comment-only change, no logic touched (within the non-goal, which scopes to
  logic).

- **A1–A4** were already conformant — no changes needed.

### Re-verification (revision 2, run after both comment fixes)
Curated CI-parity venv (`/tmp/ci-venv-verify`), rebuilt exactly as CI does:
- `ruff check .` → `All checks passed!`
- `ruff format --check .` → `126 files already formatted`
- `mypy app/ migrations/` → `Success: no issues found in 75 source files`
- `pytest` **without a live DB** → `312 passed, 43 skipped`
- `pytest` **with live migrated Postgres** → `355 passed`

Full local dev venv (`uv run --no-sync pytest`, no DB) → `312 passed, 43 skipped`.
Zero collection errors at every step; nothing to root-cause.
