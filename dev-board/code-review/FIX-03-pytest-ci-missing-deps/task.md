# Task FIX-03-pytest-ci-missing-deps — Fix real backend-ci `pytest` step (27 collection errors)

- **Phase:** cross-cutting   **Status:** ENG   **Tags:** (B)/(I)

## Scope

The user ran the actual GitHub Actions `backend-ci` workflow (log captured in
`dev-board/failed_pipeline.md`) on `version-2` HEAD (commit `5b83e49...`, which includes FIX-02). Lint, format,
mypy, and the pgvector-extension/migration steps all pass — but the **`Test (pytest)`** step
(`uv run --no-sync pytest`) fails immediately: **27 collection errors, "Interrupted: 27 errors during
collection"**, exit code 2.

**Root cause, reproduced and fully verified by the orchestrator** (do not need to re-diagnose — apply and
verify the fix below):

Every collection error is one of exactly two `ModuleNotFoundError`s, both for packages that **are** real,
declared dependencies in `backend/pyproject.toml`'s main `dependencies = [...]` list, but were **never added**
to the curated CI/Makefile install (the narrower `uv sync --only-group dev` + explicit light-package `uv pip
install` list `.github/workflows/backend-ci.yml`/`Makefile`'s `install` target use instead of a full `uv
sync`, to avoid pulling in the heavy ML stack):

1. **`authlib`** (`app/security/oidc.py:33: from authlib.common.security import generate_token`) — the real
   OIDC/PKCE client used by SSO (P3-02). `app/security/oidc.py` is imported at module scope by
   `app.bootstrap` → `app.api.auth` / `app.api.chat` → `app.main`, which is why it takes down almost every
   test module transitively (`test_health.py`, `test_chat_api.py`, `test_auth_api.py`, etc.) — 15 of the 27
   errors.
2. **`langgraph`** (`app/agents/graph.py:72: from langgraph.graph import END, START, StateGraph`) — the
   multi-agent graph library (P4). `app/agents/graph.py` is imported at module scope by
   `app/agents/__init__.py`, which nearly every P4 test and anything importing `app.agents.state`/`ChatService`
   pulls in transitively — 12 of the 27 errors.

**Why `mypy` didn't already catch this (and why FIX-02 didn't either):** `[tool.mypy] ignore_missing_imports =
true` makes a genuinely-missing import type-check as `Any` instead of failing the build — that's a valid,
intentional posture *for type-checking*. But `pytest` actually **executes** the imports at collection time;
`ignore_missing_imports` has no equivalent for a real interpreter import. FIX-02 (the prior task) verified
`mypy` against a faithful curated venv and found/fixed two *type-checking* issues, but did not also run
`pytest` against that same curated venv — it re-verified `pytest` only against the full local dev venv (which
has everything installed via a real `uv sync`, so these two `ModuleNotFoundError`s never surfaced there). That
was the gap: **verify pytest against the curated venv too, every time the curated install list might be
stale**, not just mypy.

**Both packages are lightweight — safe to curate in** (already checked): `authlib`'s own dependency footprint
is small (no ML/CUDA); `langgraph`'s `Requires:` are `langchain-core, langgraph-checkpoint, langgraph-prebuilt,
langgraph-sdk, pydantic, xxhash` — also no torch/CUDA/heavy-ML transitives. Adding them does **not** violate
the documented "keep CI light" intent (that intent is specifically about excluding `sentence-transformers`/
`torch`/`docling`, per the workflow's own comments) — it was simply an oversight that these two *were* excluded
along with the genuinely-heavy libs.

## Fix

Add `authlib` and `langgraph` to the curated install list in **both**:
1. `.github/workflows/backend-ci.yml`'s "Install dependencies" step.
2. `backend/Makefile`'s `install` target.

(Keep them in sync — same contract as FIX-02's `joserfc` addition; the Makefile's own header comment says so.)

Update the workflow's explanatory comment that currently groups `langgraph` with `docling` as "third-party
libs without published type stubs... treated as Any instead of failing the build" (`.github/workflows/
backend-ci.yml`, near the `ignore_missing_imports` mypy config / the install step comment block) — that
framing is no longer accurate for `langgraph` once it's actually installed in CI; `docling` (and
`sentence-transformers`/`torch`) remain correctly excluded and untyped.

## How to verify (do this exactly — this is what actually caught the bug)

```bash
cd backend
rm -rf /tmp/ci-venv-verify
UV_PROJECT_ENVIRONMENT=/tmp/ci-venv-verify uv sync --only-group dev
uv pip install --python /tmp/ci-venv-verify/bin/python \
  fastapi pydantic pydantic-settings "celery[redis]" openai \
  sqlalchemy asyncpg aiosqlite pgvector alembic joserfc authlib langgraph   # your updated curated list

/tmp/ci-venv-verify/bin/ruff check .
/tmp/ci-venv-verify/bin/mypy app/ migrations/

# Full parity with real CI, including the live-DB step (mirrors backend-ci.yml's service container):
docker compose -f ../docker-compose.yml up -d --wait db
set -a && . ../.env && set +a
export DATABASE_URL="postgresql+asyncpg://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:5432/$POSTGRES_DB"
export HF_API_TOKEN=ci-not-a-real-token JWT_SECRET_KEY=ci-not-a-real-secret
/tmp/ci-venv-verify/bin/python -m alembic upgrade head
/tmp/ci-venv-verify/bin/python -m pytest
docker compose -f ../docker-compose.yml down
```
This must show **zero collection errors** and the full suite passing (355 tests with a live, migrated DB; 312
passed + 43 skipped without one) — this is the faithful reproduction of what CI's `pytest` step actually sees.
A bare `uv run --no-sync pytest` against your already-`uv sync`'d full local dev venv will falsely pass
regardless of curated-install gaps — do not rely on it alone as your final check for this task.

## Acceptance criteria

- [ ] `pytest` collects and runs with **zero** `ModuleNotFoundError`/collection errors against a **freshly
      built venv that mirrors CI's exact curated install steps** (see verification command above).
- [ ] `.github/workflows/backend-ci.yml` and `backend/Makefile`'s `install` target both updated identically.
- [ ] The stale "langgraph... treated as Any" comment is corrected/updated to reflect that langgraph is now
      actually installed in CI (only docling/sentence-transformers/torch remain excluded-and-Any).
- [ ] Full backend test suite green against **both** the full local dev venv and the curated venv (with and
      without a live DB) — no regression.
- [ ] `ruff`/`ruff format --check`/`mypy` all still clean in the curated venv too (not just pytest).

## Design references

- `dev-board/failed_pipeline.md` — the actual failing CI log this task fixes (27 collection errors at the
  `pytest` step).
- `.github/workflows/backend-ci.yml`, `backend/Makefile` — the two install lists that must stay in sync.
- `backend/pyproject.toml` — `authlib`/`langgraph` are already correctly declared as main dependencies here;
  this task only fixes the curated-CI subset list, not the dependency declarations themselves.
- `dev-board/code-review/FIX-01-backend-test-deps/`, `FIX-02-mypy-ci-curated-deps/` — the precedent for this
  exact class of "curated CI venv vs. full local venv" dependency-gap bug, and why re-verifying **each**
  affected tool (lint/format/mypy/pytest) against the curated venv — not just the one that was reported
  broken last time — matters.

## Constraints / non-goals

- Do NOT add `sentence-transformers`, `torch`, or `docling` to curated CI — those remain deliberately excluded
  (genuinely heavy/ML, unlike `authlib`/`langgraph`).
- Do NOT change `app/security/oidc.py` or `app/agents/graph.py` logic — this is a curated-install-list fix
  only, the code itself is correct (it declares these as real dependencies; the CI install list just didn't
  match).
- Do NOT silence the failure with test skips/xfails — install the real, already-declared dependencies.
