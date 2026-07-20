---
name: project-compose-shared-context-stale-images
description: backend/worker/beat are separate compose image tags built from the same ./backend context — rebuild all three together or the worker runs stale code
metadata:
  type: project
---

`backend`, `worker`, and `beat` compose services all `build:` from `./backend` but each gets its
**own** image tag (`career-coach-agent-{backend,worker,beat}`).

**Why:** compose builds one image per service even when the context/Dockerfile are identical.
Rebuilding only `backend` leaves `worker`/`beat` on a **stale** image (old `app/` code + old deps —
e.g. no `opentelemetry` package), which silently breaks anything the worker does (during P11-04
the worker exported zero OTel spans until rebuilt).

**How to apply:** for any live-infra verification/build task, rebuild all three together
(`docker compose build backend worker beat`) whenever backend code or `pyproject.toml` changes, and
verify inside the actual worker container (`compose exec worker python -c "import <pkg>"`) — don't
assume a `backend` rebuild propagated. Related: [[project-local-venv-partial]], [[project-live-docker-stack]].
