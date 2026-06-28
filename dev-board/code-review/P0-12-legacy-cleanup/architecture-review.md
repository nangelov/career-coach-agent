# Architecture review — P0-12-legacy-cleanup · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 target structure | v2 lives in `backend/` + `frontend-v2/`; v1 must not pollute the target tree | All 30 v1 source files relocated to `legacy-code/`; `backend/`/`frontend-v2/` untouched | None |
| A2 | Decoupling (task scope) | Nothing in v2 imports v1 | `grep` for `tools/`/`helpers/`/`output_parser`/`legacy-code` across `backend/`+`frontend-v2/` (excl. node_modules) is empty | None |
| A3 | Phase fit — move-not-delete | plan.md P11 owns v1 *deletion*; P0 does the *move* | Done via `git mv` (30 `R` renames, history preserved); deletion correctly deferred | None |
| A4 | Locked v2 decisions | ReAct parser deleted in v2; no LangChain ReAct in active tree | `output_parser.py`/`prompts.yaml`/v1 `tools` now isolated under `legacy-code/`, out of the v2 import path | None |
| A5 | Build integrity | `docker-compose.yml` builds only from v2 contexts | compose references `./backend` + `./frontend-v2` only; `docker compose config` → VALID after the root `Dockerfile` move | None |
| A6 | CI phase fit (P0-09/P0-10) | Moving root files must not break CI workflows | `.github/` has zero references to moved root paths (`requirements.txt`, `main.py`, `app.py`, `frontend/`, `Dockerfile`) | None |
| A7 | Reference hygiene | `legacy-code/README.md` marks folder reference-only | Present; accurate inventory + "not used by v2", "deletion deferred to P11" | None |

## Cross-cutting checks
- [x] Fits target structure (§8) — v2 stays in `backend/` + `frontend-v2/` (latter blessed during coexistence, see Notes); v1 fully quarantined.
- [x] Honors locked decisions — v1 ReAct parser/prompt/tools moved out of the active tree; no Postgres/Redis/SSO/embedding decisions touched (pure move).
- [x] Interfaces-before-implementations — N/A (no code authored).
- [x] Budget posture respected — N/A (no new deps/services).

## Notes
- **Root `Dockerfile` move is correct but carries a P11 deployment dependency.** HF Spaces builds a Space from a root-level `Dockerfile`; this branch (`version-2`) now has none. That is fine here — v2 deploys via `docker-compose` and the cutover is explicitly **P11**, and this is not `main`. Flagging for the P11 gate: the deploy target (compose vs. a new root Dockerfile for Spaces) must be settled there. Ties to the frontend-path rename already owed at P11 (`frontend-v2/` → `frontend/`).
- **Gitignored cruft left in place** (root `__pycache__/`, empty `data/`) is correctly out of scope — not v1 source, untracked, no effect on the tracked repo or v2. A cleanliness call for the code-reviewer, not a design gap.
- `git status` shows `M docker-compose.yml` / `M CLAUDE.md`, but these reflect prior uncommitted P0 work on this branch, not this task — engineer claims them untouched and the compose contents confirm no dependency on moved paths. No conformance concern.
