# Task P0-12-legacy-cleanup — Move all v1 legacy code into legacy-code/ for reference

- **Phase:** P0   **Status:** ENG   **Tags:** (I)

## Scope

Move every v1 file/folder into a top-level `legacy-code/` directory so it is available for reference
but is completely decoupled from the v2 codebase. Nothing inside `legacy-code/` should be imported
or used by `backend/` or `frontend/`.

### What to move (v1 artefacts at repo root level)
Move these into `legacy-code/` preserving their relative structure:
- `app.py`
- `main.py`  (v1 uvicorn entry point)
- `output_parser.py`
- `prompts.yaml`
- `requirements.txt`
- `helpers/`   (v1 helper modules)
- `tools/`     (v1 LangChain tools)
- `frontend/`  (old CRA frontend — do NOT touch `frontend/`)
- `Dockerfile` (v1 Dockerfile, if present and not already the v2 one)

### What NOT to move
- `backend/`           — v2 backend (keep in place)
- `frontend/`       — v2 frontend (keep in place)
- `docker-compose.yml` — v2 compose file (keep in place)
- `.github/`           — CI workflows (keep in place)
- `dev-board/`         — planning docs (keep in place)
- `.claude/`           — agent config (keep in place)
- `.env`, `.env.example`, `.gitignore`, `README.md`, `CLAUDE.md` — keep at root

### Additional steps
1. Add a `legacy-code/README.md` with one paragraph explaining: "This folder contains the v1 codebase,
   preserved for reference. It is not used by the v2 application."
2. Verify no `backend/` or `frontend/` file imports anything from `legacy-code/`.
3. List every file moved in `engineer.md`.

## Acceptance criteria

- [ ] `legacy-code/` directory exists at the repo root.
- [ ] All v1 files listed above are inside `legacy-code/` (check with `ls legacy-code/`).
- [ ] `backend/` and `frontend/` have zero imports referencing `legacy-code/` (grep check).
- [ ] `legacy-code/README.md` exists with the reference-only note.
- [ ] Repo root is clean — only v2 artefacts + `legacy-code/` + config files remain at the top level.
- [ ] `docker compose config` still validates (nothing the compose file needed was moved).

## Design references

- `dev-board/plan.md` — P11 "Delete v1: app.py, output_parser.py, old CRA frontend/, etc." (this task does the move now; deletion comes at P11 cutover)
- `dev-board/app-design-and-features.md` — §8 backend structure (v2 lives in `backend/`)
- `CLAUDE.md` — "v1 description … stays accurate until v2 lands" (v1 is reference, not active)

## Constraints / non-goals

- Do NOT delete v1 files — move only. Actual deletion is deferred to P11.
- Do NOT modify any v1 code inside `legacy-code/`.
- Do NOT modify `backend/`, `frontend/`, `docker-compose.yml`, or `.github/` workflows.
