---
name: project-mypy-strict-gotchas
description: Recurring fixes needed to make `mypy --strict` pass in the v2 backend (pydantic, celery, starlette)
metadata:
  type: project
---

The v2 backend runs `mypy --strict` in CI (P0-09). Three recurring strict-mode
issues and their standard fixes:

- **pydantic-settings `Settings()` flagged "missing required argument".** Add
  `plugins = ["pydantic.mypy"]` to `[tool.mypy]` so the plugin understands fields
  are env-populated, not constructor args.
- **`@celery_app.task` decorator → "untyped decorator makes function untyped".**
  Celery ships no `py.typed`; add `celery-types` to the dev dependency group so the
  decorators type-check (cleaner than per-module `disallow_untyped_decorators`).
- **starlette 1.3+ `Request` is generic** (over `StateT`). Under strict `type-arg`,
  annotate as `Request[Any]`. Middleware `dispatch` must be fully typed:
  `async def dispatch(self, request: Request[Any], call_next: RequestResponseEndpoint) -> Response`.

Also: `ignore_missing_imports = true` keeps un-installed third-party libs (langgraph,
docling, etc.) as `Any` so CI need not install the heavy ML stack to type-check
first-party code. mypy `python_version` is kept at **3.11** to match `requires-python`
/ the Dockerfile, not 3.12. See [[project-python-version]].
