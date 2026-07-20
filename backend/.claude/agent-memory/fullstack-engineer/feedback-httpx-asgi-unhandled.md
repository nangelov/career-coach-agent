---
name: feedback-httpx-asgi-unhandled
description: Testing an endpoint that raises an unhandled exception via httpx ASGITransport; and NoReturn handlers need response_model=None
metadata:
  type: feedback
---

Two FastAPI/httpx test gotchas hit while wiring an admin-gated "throw a test error" endpoint.

**Rule 1 — unhandled exceptions propagate through httpx `ASGITransport`.** Unlike Starlette's
`TestClient`, `httpx.ASGITransport` has **no** `raise_server_exceptions` kwarg. Starlette's
`ServerErrorMiddleware` emits the 500 AND re-raises, so the original exception reaches the test.
Assert with `with pytest.raises(MyError): await client.get(...)`, not `assert resp.status_code == 500`.

**Rule 2 — a handler annotated `-> NoReturn` (only ever raises) needs `@router.get(..., response_model=None)`.**
FastAPI otherwise tries to build a Pydantic response field from `NoReturn` and raises
`FastAPIError: Invalid args for response field`.

**Why:** both cost a red test on the way to green for the P11-02 Sentry-test endpoint.
**How to apply:** any deliberately-erroring / raise-only endpoint (debug/verify hooks). See
[[phase-exit-verification]] for the broader compose-real-stack testing pattern.
