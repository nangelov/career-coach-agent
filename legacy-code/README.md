# Legacy code (v1)

This folder contains the **v1 codebase**, preserved for reference only. It is **not used by the v2
application** — nothing under `backend/` or `frontend/` imports from or depends on anything here.
The v1 files were relocated unmodified (via `git mv`, so history is preserved) during P0-12; actual
deletion is deferred to the P11 cutover. Do not import from this folder or modify its contents.

## What lives here

- `app.py` — v1 FastAPI app + dual LangChain ReAct agents
- `main.py` — v1 uvicorn entry point
- `output_parser.py` — v1 ReAct output-parser (removed entirely in v2)
- `prompts.yaml` — v1 system prompt (tightly coupled to the ReAct parser)
- `requirements.txt` — v1 Python dependencies
- `Dockerfile` — v1 single-image build (Python + CRA frontend)
- `helpers/` — v1 helper modules (PDF builders, feedback handler, input sanitiser)
- `tools/` — v1 LangChain tools
- `frontend/` — v1 Create-React-App frontend (superseded by `frontend/`)
