# Code review — FIX-01-backend-test-deps · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | backend/uv.lock | Unmentioned churn not listed in engineer.md "Files changed": `openai` requires-dist `>=1.12.0`→`>=2.0.0` plus CUDA platform-marker re-resolution across ~10 nvidia packages. Side-effect of running `uv sync` during `make install`. Harmless (the bump only re-syncs a lock that was stale vs `pyproject.toml`, which already pins `openai>=2.0.0`; no app behavior change), but undocumented scope. | Either keep and note it in `engineer.md` as an intentional lock re-sync, or revert the lockfile so the commit stays scoped to the CI/Makefile fix. No source change required. |
| C2 | nit | dev-board/code-review/FIX-01-backend-test-deps/engineer.md:6-8 | Part A narrative implies the Makefile `install`/`test` targets pre-existed and merely "carried the same curated-list drift." They did not exist at HEAD (only migration targets did) — they were newly created here. The fix itself is good; only the description is slightly off. | Clarify wording; no code change. |

## Notes
Core fix verified end-to-end against the actual diffs:

- **`.github/workflows/backend-ci.yml`** — `pgvector` added to the curated `uv pip install` list and the explanatory comment updated to say why (P2-04/P2-06 `pgvector.sqlalchemy.Vector`, imported transitively at collection). Matches the confirmed root cause in the real CI logs (`ModuleNotFoundError: No module named 'pgvector'` from `app/repositories/models/knowledge.py:62`). YAML validates. This is the correct, minimal fix. Confirmed the only third-party collection-time imports reachable via `app/repositories` are `fastapi`, `sqlalchemy`, `pgvector`, `redis` — all in the curated list (`redis` transitively via `celery[redis]`), so the list is complete for collection.
- **`backend/Makefile`** — `pgvector` added to the curated list, plus new `install`/`lint`/`format`/`format-check`/`typecheck`/`test`/`test-integration`/`check` targets. Keeps `make install` in sync with CI (DRY on the curated list) and gives contributors an enforced correct-venv path (`uv run --no-sync`), which directly satisfies the Part A acceptance criterion (a documented/Makefile way to run tests so the wrong-venv failure doesn't recur).
- **`backend/tests/conftest.py`** — scrutinized per the specific ask: `git diff HEAD` is **empty**, i.e. the file now matches the committed baseline exactly. The "restore" removed a stray uncommitted working-tree edit; there is no net change and no behavior change to the settings-seeding fixture. Passes `ruff check`. Confirmed genuinely a formatting restore, not a disguised behavior change.

Independently reproduced (not just trusting pasted output):
- Full suite in the project venv: **102 passed, 40 skipped** (matches claim).
- Test collection: **142 collected, 0 errors**.
- All **40 skips** confirmed via `pytest -rs` to be the identical live-Postgres integration gate (`Postgres not reachable at DATABASE_URL — integration test skipped`), with per-module counts exactly as reported (conversation_store 4, identity 6, knowledge 9, p2_exit 5, structured 10, vector_search 6). Expected-by-design; not hiding broken code (unit paths for the same layers run unconditionally, and `make test-integration` runs all 40 against the live DB).

The deferred follow-up (add a Postgres `services:` container to CI so integration tests execute rather than skip) is correctly scoped out per the P0-09 free-tier posture and flagged, not silently dropped. Acceptance criteria all met. Findings are minor/nit only — housekeeping, no functional defect.
