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
- **`base ** n` with a *variable* int exponent is typed `Any`** (negative exponents
  yield float, so mypy widens `int ** int` → `Any`), which trips `no-any-return`
  when the result is returned as `float`. Fix: make the base a float literal —
  `x * (2.0 ** (n - 1))` — so the expression stays `float`. Seen in exponential
  backoff helpers.
- **`AsyncSession.execute(delete(...))` → `Result[Any]` has no `rowcount`.** For a
  Core `delete()`/`update()` where you need the affected-row count, `execute` is typed
  as returning `Result`, not `CursorResult`. Fix: `cast("CursorResult[Any]", result).rowcount`
  (`from sqlalchemy import CursorResult`). Used for scoped delete → bool ("did we own/remove a row").

Also: `ignore_missing_imports = true` keeps un-installed third-party libs (langgraph,
docling, etc.) as `Any` so CI need not install the heavy ML stack to type-check
first-party code. mypy `python_version` is kept at **3.11** to match `requires-python`
/ the Dockerfile, not 3.12. See [[project-python-version]].
