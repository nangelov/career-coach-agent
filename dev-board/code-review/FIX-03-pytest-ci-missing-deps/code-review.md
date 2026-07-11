# Code review — FIX-03-pytest-ci-missing-deps · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| — | — | — | No blocking, major, minor, or nit findings. | — |

## Notes
Independently reproduced the fix against a **fresh curated venv** (not the full local dev venv), built
exactly as CI does: `uv sync --only-group dev` + `uv pip install ... joserfc authlib langgraph`.

Verified all five acceptance criteria:
- **Zero collection errors:** `pytest --collect-only` → `355 tests collected in 2.82s`, no
  `ModuleNotFoundError`. The 27 collection errors are gone.
- **Suite green (curated venv, no live DB):** `312 passed, 43 skipped` — matches the engineer's reported
  numbers exactly. This is the real check the task called out (a bare `uv run --no-sync pytest` against the
  full dev venv would have falsely passed).
- **No other runtime import gaps surfaced at execution.** The curated list still omits several declared deps
  (redis, langmem, reportlab, google-search-results, uvicorn); confirmed none is imported at module scope on
  the collection/execution path, so the suite runs clean with just `authlib`+`langgraph` added. Only the two
  genuinely-missing packages were needed.
- **CI-light intent preserved:** confirmed in the built venv that `torch`, `sentence_transformers`, and
  `docling` are still absent; only `authlib` and `langgraph` (+ light transitives: langchain-core,
  langgraph-*, xxhash) were pulled in. No heavy/ML stack leaked in.
- **List parity:** the `install` lines in `.github/workflows/backend-ci.yml` and `backend/Makefile` are
  byte-identical (`... joserfc authlib langgraph`) — the sync contract both files document is honored.
- **Other curated-venv tools still clean:** `ruff check` → all passed; `ruff format --check` → 126 files
  already formatted; `mypy app/ migrations/` → success, 75 source files.
- **Stale comment corrected:** the workflow no longer describes `langgraph` as excluded-and-`Any`; the
  mypy-step comment now correctly scopes the excluded-untyped set to docling/sentence-transformers/torch.
  Accurate.

Scope discipline is good: no application code touched (`app/security/oidc.py` / `app/agents/graph.py`
untouched), no test skips/xfails — the real declared deps were simply curated into CI, matching the
FIX-01/FIX-02 precedent. No security surface (CI config + install list only).

Non-blocking observation (not a finding, not the engineer's to gate on): the untracked
`dev-board/failed_pipeline.md` is a captured CI log referenced by the task; the orchestrator may want to
decide whether it belongs in version control.
