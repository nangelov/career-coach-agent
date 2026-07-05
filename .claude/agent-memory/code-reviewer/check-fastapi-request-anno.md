---
name: check-fastapi-request-anno
description: FastAPI dependency params annotated Request[Any] break Depends() at route registration; use bare Request in deps
metadata:
  type: project
---

In this backend the convention is to annotate `Request[Any]` (Starlette Request is generic; keeps mypy `--strict`/`disallow_any_generics` happy). That is fine for **Starlette middleware** `dispatch(self, request: Request[Any], ...)` — Starlette calls it directly, FastAPI never analyzes the signature.

**But for a FastAPI *dependency* function** (anything reached via `Depends(...)`), a param typed `Request[Any]` breaks route registration: FastAPI only auto-injects the raw request when the param is the **bare `Request` class** (`lenient_issubclass(ann, Request)`). The subscripted `Request[typing.Any]` is a `_GenericAlias`, not the class, so FastAPI treats it as a body/query field and raises `FastAPIError: Invalid args for response field! ... is a valid Pydantic field type` at import/registration time.

**Why:** caught in P2-01 — `get_db_session(request: Request[Any])` passed mypy + all unit tests (tests called it directly, bypassing DI) but `Depends(get_db_session)` on any route raised `FastAPIError`. The delivered "FastAPI dependency" was unusable as one.

**How to apply:**
- Any dependency function that takes the request → param must be **bare `Request`** (verified: bare `Request` passes this project's mypy `strict=true` cleanly, so there is no type-arg tension to trade off).
- When a review claims a DB/request-scoped FastAPI dependency works but no test wires it via `Depends`/`TestClient`, treat that as a test gap — unit tests that call the dependency function directly do NOT exercise FastAPI's parameter analysis and give false confidence. Ask for an integration test that registers it with `Depends`.
- Grep the diff for `Request[Any]` and check whether each site is middleware (ok) or a `Depends`-reached dependency (must be bare `Request`).
