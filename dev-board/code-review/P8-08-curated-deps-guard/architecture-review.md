# Architecture review — P8-08-curated-deps-guard · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Guard scope (task Design §1) | Static diff of `pyproject.toml` runtime deps vs curated CI/Makefile lists, respecting an ML/lazy allowlist — not import-walking | `check_curated_deps.py` parses `[project].dependencies` via stdlib `tomllib`, extracts curated names from both files, diffs against curated ∪ dev-group ∪ allowlist | None |
| A2 | Single source of truth (Design §2) | Enforce CI list == Makefile list | `find_problems` fails on any set difference between the two curated lists | None |
| A3 | Wiring (Design §3) | Early CI step before install/pytest; stdlib-only so it runs pre-venv; mirrored in Makefile | Step added after Python setup, before install (`python3 scripts/check_curated_deps.py`); `make check-deps` prepended to `make check`; no third-party imports | None |
| A4 | Fail message (Design §4) | Names the exact missing package(s) | Per-package messages naming pkg + remediation (curate in both lists or allowlist with reason) | None |
| A5 | Non-goal / budget posture (Constraints; §11) | Guard *around* curated design; must NOT switch CI to full `uv sync` (keeps heavy ML stack — torch/docling — out of the free-tier venv) | Direction is one-way (declared-but-not-curated only); ML stack stays on the intentional-exclusion allowlist; no `uv sync` change | None |
| A6 | Target structure (§8) | Tooling/scripts co-located with existing backend scripts | Placed in `backend/scripts/` alongside `check_celery.py`, `check_pgvector.py`; test in `backend/tests/` — consistent convention | None |
| A7 | Locked decisions | Postgres+Redis-only, in-process ML embeddings, LangGraph — all unaffected; ML-exclusion posture preserved | CI-only change, no product code touched; allowlist keeps sentence-transformers/docling/torch excluded as designed | None |

## Cross-cutting checks
- [x] Fits target structure (§8) — `scripts/` + `tests/`, no layering surface touched (Router→Service→Repo untouched)
- [x] Honors locked decisions — ML stack stays out of curated venv; no full `uv sync`; Postgres+Redis-only intact
- [x] Interfaces-before-implementations — N/A (tooling task, no runtime seams)
- [x] Budget posture respected — preserves the free-tier curated-install design the guard exists to protect

## Notes
- Verified green locally: guard exits 0 ("curated CI/Makefile lists cover every runtime dep"); `pytest tests/test_curated_deps.py` → 9 passed. All 22 runtime deps resolve to curated (12), dev-group (`httpx`), or allowlist (9).
- The `redis` allowlist entry is subtle but confirmed accurate: `redis.asyncio` is imported at *module scope* (`app/bootstrap.py:28`, `app/repositories/redis.py:33`), so it IS hit at pytest collection — it passes today only because `celery[redis]` pulls redis-py transitively into the curated venv. Design risk / follow-up (minor, cheap to fix later): this coverage is implicit — if celery ever drops the `redis` extra or the transitive redis-py diverges, the guard would still report clean while CI could break. Consider promoting `redis` to an explicit curated entry rather than relying on the transitive; not a blocker for this task.
- Direction-is-one-way and the stale-allowlist honesty check are good conformance additions — they keep the guard itself from rotting, matching the "can't recur silently" intent of the task.
