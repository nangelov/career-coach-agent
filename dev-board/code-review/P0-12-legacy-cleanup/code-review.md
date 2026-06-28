# Code review — P0-12-legacy-cleanup · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | repo root `__pycache__/`, `data/` | Leftover v1 runtime dirs still sit at the repo root after the move; engineer flagged them in `engineer.md` §Key decisions. Both are gitignored + untracked (confirmed via `git check-ignore` and `git ls-files`), so they do not affect the tracked repo or v2. | Optional: delete the stale `__pycache__/` and empty `data/` to fully tidy the root. Out of the task's move list, so deferring is acceptable. |

## Notes

Verified against all acceptance criteria — every one passes:

- **legacy-code/ exists + all v1 artefacts inside** — `ls legacy-code/` shows `Dockerfile app.py frontend/ helpers/ main.py output_parser.py prompts.yaml requirements.txt tools/ README.md`. Matches the task's move list exactly.
- **Moves recorded as renames (history preserved)** — `git status --short` shows 33 `R` entries (the 30 tracked v1 files + the 3-file expansion of `helpers`/`tools`/`frontend` subtrees); no `D`+`A` churn for v1 source. `git mv` was used as the engineer claims.
- **Zero v2 references to legacy** — `grep -rn "legacy-code\|legacy_code" backend/ frontend-v2/` → clean (exit 1). `grep -rnE "from tools|import tools|from helpers|import helpers|output_parser" backend/ frontend-v2/` → clean (exit 1). The `from app.main import app` hit in backend is the v2 backend's own `backend/app/` package, not the moved root `app.py`.
- **README present + reference-only** — `legacy-code/README.md` explicitly states "preserved for reference only … not used by the v2 application … Do not import from this folder."
- **docker compose still validates** — `docker compose config` → VALID. Compose builds only from `./backend` and `./frontend-v2` contexts (verified), so relocating the root v1 `Dockerfile` and other v1 files is safe; nothing compose needs was moved.
- **Repo root clean** — no stray tracked v1 source remains at root (`git ls-files` filtered to root shows only v2 artefacts + config + legacy-code/). Only gitignored cruft (`.venv/`, `.ruff_cache/`, `__pycache__/`, `data/`) lingers — see C1.

Security note: the v1 `python_repl.py` (ACE-risk REPL that v2 removes) is now isolated under `legacy-code/tools/python_repl.py`, no longer at root `tools/`, and is not imported by any v2 code — consistent with the locked decision to drop `run_python_code` in v2.

Out of scope for this review: the working tree also shows `D` deletions of `.claude/dev-board/*` with an untracked root `dev-board/` — that is a separate dev-board relocation, not part of this task's diff (P0-12 touches only v1 file renames + `legacy-code/README.md`), so it does not affect this verdict. `legacy-code/README.md` is untracked (`??`) as expected; staging/commit is the orchestrator's/user's step, not a finding.

Pure file-move task with no logic changes — nothing to gate on.
