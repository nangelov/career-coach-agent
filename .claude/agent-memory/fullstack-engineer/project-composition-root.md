---
name: project-composition-root
description: v2 wiring conventions — composition in app/bootstrap.py (not the API layer), AppStateKeys enum for app.state, shared ORM mixins, single-home type aliases
metadata:
  type: project
---

Reviewers require these DRY/SoC conventions for backend v2 (set in CR-01 audit fix pass).

**Composition root lives in `app/bootstrap.py`, never the API layer.** `build_chat_service`
and any future service assembly go here. API routers (`api/*.py`) must stay thin: import
**no** repository/LLM types — only the `get_*_service` FastAPI dependency (which delegates to
bootstrap) + request/response/SSE plumbing. The lifespan (`app/main.py`) owns the ASGI app +
eager pool build + shutdown teardown.

**`app.state` attribute names come from `AppStateKeys(StrEnum)` in `app/app_state.py`** — never
bare string literals. That module is dependency-free (low-level) so main/bootstrap/api/
repositories can all import it without circular deps. `StrEnum` members are `str`, so pass them
straight to `getattr`/`setattr(app.state, AppStateKeys.X, ...)`.

**Adapters take config via a `from_settings(...)` classmethod + keyword-only ctor params with
defaults** (match `RedisSessionMemory`/`RedisCancelRegistry`). Never read the global `settings`
inside a method body — inject at construction. The composition root builds via `from_settings`.

**Shared ORM plumbing goes in `app/repositories/models/_mixins.py`** (e.g. `CreatedAtMixin`),
imported by every table-group module — no per-module copies.

**A shared type alias has ONE home.** `ToolSchema = dict[str, Any]` lives in the SDK-free
`app/llm/types.py` and is re-exported (via `__all__`) from `llm/client.py` and `tools/base.py`.
Keep the dependency direction correct: to link two constants across layers that must not import
each other (e.g. `EmbeddingClient.DIMENSION` vs models' `EMBEDDING_DIM`), assert equality in a
**test**, don't add a cross-layer import.

**Don't silently default injected ports.** If a service allows omitting a port (e.g.
`SessionMemory`/`CancelRegistry` for tests), emit `logger.warning` on the in-memory fallback so a
mis-wired production composition can't silently reintroduce v1 global state. See
[[project-live-docker-stack]] for verifying wiring against the real stack.

**Shared test fakes go in `tests/fakes.py`** (`FakeRouter`/`FakeRegistry`/`Script`), imported
everywhere — don't re-declare per test module (causes drift).
