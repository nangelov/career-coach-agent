# Architecture review — P9-11-cicd-verify · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Verify-task fidelity (task.md steps 1-3) | Run the *exact* CI command sets, not approximations | Engineer's pasted `uv pip install` list is byte-identical to `.github/workflows/backend-ci.yml` L130-132; ruff/ruff-format/mypy/pytest invocations match L136-183 | none |
| A2 | Curated-deps guard (P8-08) | CI list == Makefile == every runtime import; guard green | `python3 scripts/check_curated_deps.py` → OK; guard enforces CI/Makefile parity | none |
| A3 | langmem curated question (task focus) | Confirm whether P9 imports `langmem`/`trustcall` at runtime | `grep -rn langmem app/ tests/` → **no hits**; only declared in `pyproject.toml` L28. Correctly excluded via `INTENTIONAL_EXCLUSIONS` ("declared but not yet imported"). A CI-fresh curated venv imports all P9 memory modules. **PASS — no gap** | none (see Note N1) |
| A4 | Migration posture (§8, explicit-step) | New P9 migration applies to head cleanly; migrations never auto-run | `alembic upgrade head` → 0001→**0009** (0009 = P9-01 `message_feedback.message_id` unique); P9-08 beat is a compose service, no schema change — consistent with "beat = service only" | none |
| A5 | Live-PG exit-verify (P9-10, prior verify precedent) | `test_p9_exit_verification.py` must **execute** against live Postgres, not skip | Ran on standalone `pgvector/pgvector:pg16` with CI creds/env → **8/8 executed**; full suite 956 passed, 4 skipped (standing heavy-ML docling×3/pytesseract×1, unchanged posture) | none |
| A6 | Target structure (§8) | Memory surface under `app/memory/`, feedback under `services/`, tasks under `tasks/`, api under `api/` | Modules present in correct packages; no layering change; verification-only, zero source edits | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — no source/config change; verify-only task
- [x] Honors locked decisions — Postgres+pgvector only (migration 0009 clean), Celery beat as compose service, no ReAct parser touched, curated venv excludes heavy ML/CUDA
- [x] Interfaces-before-implementations — `app/memory/store.py` conforms to `langgraph.store.base.BaseStore` (already-curated seam), not a langmem lock-in
- [x] Budget posture — langmem correctly kept out of the free-tier CI install; no paid deps added

## Notes
- **N1 (design-record follow-up, not a blocker):** CLAUDE.md's locked decision names **LangMem** for teachable memory, yet P9 hand-rolled extraction (`app/memory/learn.py`) and builds on the `langgraph` `BaseStore` seam instead — so `langmem` is imported nowhere and is rightly excluded from the CI curated list. This deviation belongs to the P9-02..P9-10 decision records (all DONE, reviewed there); this verify gate does not re-litigate it. One consistency item for whoever owns P9 closeout: the guard's exclusion reason "declared but **not yet** imported anywhere" reads as *temporary*. If the hand-rolled path is the final design (langmem never to be adopted), that reason and the `pyproject.toml` L28 dependency should eventually be reconciled (drop the dep, or restate the exclusion as intentional-permanent) to prevent future drift confusion. Cheap to fix later — logged, not gated.
- Verification is faithful and reproducible; exact CI commands, real service container, teardown performed. P9 CI/CD is fully green with no code fix required.
