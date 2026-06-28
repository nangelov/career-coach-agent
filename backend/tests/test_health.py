"""Stub test for the ``GET /health`` liveness probe.

Exercises the ASGI app in-process via ``httpx.AsyncClient`` over ``ASGITransport``
(no network socket, no running uvicorn), which is the pattern all future
endpoint tests follow. ``asyncio_mode = "auto"`` (pyproject) means the
``async def`` test is collected and run without an explicit marker.
"""

from __future__ import annotations

import httpx
from httpx import ASGITransport

from app.main import app


async def test_health_returns_ok() -> None:
    """``GET /health`` responds 200 with a JSON body whose status is ``ok``."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
