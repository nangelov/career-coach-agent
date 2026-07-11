# Architecture review — FIX-02-mypy-ci-curated-deps · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | "keep CI light" curated-install posture (backend-ci.yml curated-install rationale block) | Fix the `PlannerNode` `valid-type` error in code, NOT by adding `langgraph` (or heavy/optional ML libs) to the curated venv | `langgraph` remains curated-absent — only `joserfc` (light, pure-Python) was added to the curated `uv pip install`. The `PlannerNode` error was fixed in `graph.py` with a `TypeAlias` marker. `grep langgraph` shows it only in `pyproject.toml` full deps + the mypy-step "same posture as langgraph/docling" note, never in a curated list | None |
| A2 | CI ↔ Makefile install contract (Makefile header: "Keep this list in sync… they must produce the same venv") | Both curated lists updated identically | Both now end `…pgvector alembic joserfc` — byte-identical `uv pip install` lines in `.github/workflows/backend-ci.yml:108-109` and `backend/Makefile:49-50` | None |
| A3 | Correct-layer curated-dep classification (task diagnosis; FIX-01 precedent) | `joserfc` = light, always-used runtime dep → curate in (mypy needs real types); it is not a heavy/optional ML lib | `joserfc` is Authlib's JOSE implementation (`from joserfc import jwt` in `app/security/tokens.py:34`, pure-Python, no torch/CUDA), same tier as sqlalchemy/asyncpg/alembic. Curating it in is consistent with the documented category split | None |
| A4 | `graph.py` typing-only, scoped fix (task non-goal: no blanket `# type: ignore`, no topology change) | Fix scoped to the alias declaration; graph topology/behavior untouched | Diff is exactly: `TypeAlias` added to the `typing` import + `PlannerNode: TypeAlias = StateNode[AgentState, Any]` + a load-bearing doc comment. No node body, edge, or routing change | None |
| A5 | Runtime floor / language-level fit | `requires-python = ">=3.11"`, mypy `python_version = "3.11"` | `typing.TypeAlias` (PEP 484, 3.10+) chosen over PEP 695 `type X = …` (3.12+). Correct for the 3.11 floor; no PEP 695 precedent in the codebase | None |
| A6 | Comment-claim accuracy (acceptance: update comments if the fix changes what they claim) | Explanatory comments stay truthful | mypy-step note "alembic… treated as Any (same posture as langgraph/docling)" is still accurate — langgraph/docling remain curated-absent/`Any`. The curated-install block gained an accurate `joserfc` rationale in the existing per-package style | None |

## Cross-cutting checks
- [x] Fits target structure (§8) — CI config + Makefile + `app/agents/graph.py` (P4-02); no code moved layers.
- [x] Honors locked decisions — LangGraph orchestration untouched; the fix preserves the typed shared-state seam (`StateNode[AgentState, Any]`) and does not route around it. No new heavy deps in CI.
- [x] Interfaces-before-implementations — `PlannerNode` alias (the planner test seam) is preserved and now correctly typed; no seam weakened.
- [x] Budget posture respected — the whole point of the fix is to keep the free-tier CI light (no ML stack pulled into the curated venv); `joserfc` is a light transitive of the already-required `authlib`.

## Notes
- The curated venv installs `joserfc` directly even though it arrives transitively via `authlib` in the full tree — correct, since the curated install deliberately does not resolve the full dep graph. This mirrors how `pgvector`/`asyncpg` are curated in explicitly.
- Correctness of the actual mypy-clean result (both venvs) is the code-reviewer's gate; from a design-conformance standpoint the two documented invariants the orchestrator flagged — (1) langgraph stays out of curated CI, (2) CI and Makefile install stay in sync — both hold.
- No design deviation to record; the fix reinforces the existing curated-install contract rather than bending it.
