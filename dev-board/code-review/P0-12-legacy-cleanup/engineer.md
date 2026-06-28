# Engineer report — P0-12-legacy-cleanup · Revision 1

## Summary
Relocated the entire v1 codebase into a new top-level `legacy-code/` directory, decoupling it from the
v2 `backend/` and `frontend/` trees. All moves were done with `git mv` so history is preserved and git
records them as renames (deletion is deferred to P11 per the task). Added `legacy-code/README.md` marking
the folder as reference-only. Verified no v2 code imports from `legacy-code/` and that `docker compose
config` still validates.

## Files changed

### Moved into `legacy-code/` (via `git mv`, history preserved — 30 tracked files)
- `app.py` → `legacy-code/app.py`
- `main.py` → `legacy-code/main.py` (v1 uvicorn entry point)
- `output_parser.py` → `legacy-code/output_parser.py`
- `prompts.yaml` → `legacy-code/prompts.yaml`
- `requirements.txt` → `legacy-code/requirements.txt`
- `Dockerfile` → `legacy-code/Dockerfile` (v1 single-image build; v2 uses `backend/` + `frontend/` build contexts)
- `helpers/` → `legacy-code/helpers/` (`__init__.py`, `feedback_handler.py`, `helper.py`)
- `tools/` → `legacy-code/tools/` (`__init__.py`, `date_and_time.py`, `google_jobs_search.py`, `internet_search.py`, `python_repl.py`, `visit_webpage.py`, `wikipedia_tool.py`)
- `frontend/` → `legacy-code/frontend/` (old CRA app — 15 files: `package.json`, `tsconfig.json`, `public/*`, `src/*`, `src/components/*`)

### Created
- `legacy-code/README.md` — one-paragraph reference-only note + inventory of what lives there.

### Untouched (per task constraints)
- `backend/`, `frontend/`, `docker-compose.yml`, `.github/`, `dev-board/`, `.claude/`, root config files (`.env`, `.env.example`, `.gitignore`, `.dockerignore`, `README.md`, `CLAUDE.md`).

## Key decisions
- **Used `git mv`, not delete+recreate.** Task design ref (plan.md P11) says deletion comes at the P11
  cutover; this task is a *move*. `git mv` preserves blame/history and the diff shows pure `R` (rename)
  entries.
- **Moved the root `Dockerfile`.** It is the v1 image (builds CRA `frontend/` + runs `main.py`). The v2
  `docker-compose.yml` builds from `./backend` and `./frontend` contexts (their own Dockerfiles), so the
  root Dockerfile is v1-only and safe to relocate — confirmed compose still validates.
- **Left gitignored runtime cruft in place.** Root `__pycache__/` (stale, regenerated build artifact from
  the now-moved modules) and empty `data/` (v1 feedback runtime dir) are both gitignored and untracked, not
  v1 *source*, and not in the task's move list. Left them to honor "move only what's listed / do only what
  the task asks"; flagging here in case the reviewer wants them removed too. They do not affect the tracked
  repo or the v2 app.

## How to verify
```bash
# 1. legacy-code/ exists with all listed v1 artefacts
ls legacy-code/
#    -> Dockerfile app.py frontend helpers main.py output_parser.py prompts.yaml README.md requirements.txt tools

# 2. No v2 code references legacy-code (excluding vendored node_modules)
grep -rn "legacy-code\|legacy_code" backend/ frontend/ \
  --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=dist --exclude-dir=build
#    -> no output (exit 1)

# 3. No v1 module imports leaked into v2 (the only hit, backend "from app.main import app",
#    is the v2 backend's own app package at backend/app/main.py — not the moved root app.py)
grep -rn -E "from tools|import tools|from helpers|import helpers|output_parser" backend/ frontend/ \
  --exclude-dir=node_modules
#    -> no output (exit 1)

# 4. README present
cat legacy-code/README.md

# 5. compose still validates
docker compose config >/dev/null && echo VALID

# 6. moves are recorded as renames (history preserved)
git status --short | grep '^R'
```

## Self-check
- [x] Meets acceptance criteria:
  - `legacy-code/` exists at repo root ✔
  - all listed v1 files inside `legacy-code/` ✔ (`ls legacy-code/` confirms)
  - `backend/`/`frontend/` have zero imports referencing `legacy-code/` ✔ (grep clean)
  - `legacy-code/README.md` exists with reference-only note ✔
  - repo root clean (only v2 artefacts + `legacy-code/` + config; remaining items are gitignored
    `__pycache__`/`data`/`.venv`/`.ruff_cache`) ✔ (noted above)
  - `docker compose config` validates ✔ (`VALID`)
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (no v2 code touched — pure move)
- [x] Tests/lints pass (paste result): no code changed in `backend/`/`frontend/`, so no test suite is
  affected. Validation run:
  - `docker compose config` → `VALID`
  - `grep` for legacy refs in v2 → clean (exit 1)
  - `git status` → all 30 v1 files shown as `R` renames; `legacy-code/README.md` untracked (new)

## Response to review (revisions only)
N/A — first revision.
