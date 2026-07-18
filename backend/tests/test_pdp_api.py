"""API tests for the PDP surface (P7-03, §5.2 / §9).

Overrides :func:`~app.api.pdp.get_pdp_service` (and the auth / rate-limit deps) with fakes so no
real HF/Postgres/Redis wiring runs. Asserts the router contract end-to-end: auth is required
(401) and guests are rejected (403); a generated plan returns the styled PDF with the right
content-type, filename and ``X-PDP-Status`` header; a missing profile is a 422; an exhausted plan
is a 502; an unmined role still returns a PDF (stamped ``role_profile_missing``); and an
over-budget caller gets 429.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest_asyncio
from httpx import ASGITransport

from app.api.pdp import get_pdp_service
from app.main import app
from app.security.dependencies import get_rate_limit_service, require_auth
from app.services.pdp import PdpGenerated, PdpGenerationFailed, PdpProfileMissing
from app.services.rate_limiting import InMemoryRateLimiter, RateLimitService
from tests.fakes import fake_current_user, unlimited_rate_limit_service

_PDF_BYTES = b"%PDF-1.4 fake pdf bytes"


class FakePdpService:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return self._outcome


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _capped_rate_limit_service() -> RateLimitService:
    """A real service over an in-memory limiter with a zero budget (every call is denied)."""
    return RateLimitService(
        InMemoryRateLimiter(),
        guest_message_limit=0,
        guest_upload_limit=0,
        guest_window_seconds=60,
        user_message_limit=0,
        user_upload_limit=0,
        user_window_seconds=60,
    )


async def test_requires_auth_401(client: httpx.AsyncClient) -> None:
    # No require_auth override → the real dependency rejects the missing bearer token.
    app.dependency_overrides[get_pdp_service] = lambda: FakePdpService(PdpProfileMissing())
    try:
        response = await client.post("/api/pdp", json={"career_goal": "Data Scientist"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401


async def test_guest_rejected_403(client: httpx.AsyncClient) -> None:
    service = FakePdpService(PdpGenerated(pdf=_PDF_BYTES, pdp_id="p1", status="ok"))
    app.dependency_overrides[get_pdp_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: fake_current_user("g1", role="guest")
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        response = await client.post("/api/pdp", json={"career_goal": "Data Scientist"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403
    assert service.calls == []  # rejected before any generation


async def test_happy_path_returns_pdf(client: httpx.AsyncClient) -> None:
    service = FakePdpService(PdpGenerated(pdf=_PDF_BYTES, pdp_id="p1", status="ok"))
    app.dependency_overrides[get_pdp_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "s1", role="user", user_id="u1"
    )
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        response = await client.post(
            "/api/pdp",
            json={"career_goal": "Data Scientist", "target_date": "2027-01-01"},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-pdp-status"] == "ok"
    assert "PDP_Data-Scientist.pdf" in response.headers["content-disposition"]
    assert response.content == _PDF_BYTES
    # The verified token subject (not a body field) is what the service is called with.
    assert service.calls[0]["user_id"] == "u1"
    assert service.calls[0]["career_goal"] == "Data Scientist"


async def test_unmined_role_still_returns_pdf_with_status_header(client: httpx.AsyncClient) -> None:
    service = FakePdpService(
        PdpGenerated(pdf=_PDF_BYTES, pdp_id="p2", status="role_profile_missing")
    )
    app.dependency_overrides[get_pdp_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "s1", role="user", user_id="u1"
    )
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        response = await client.post("/api/pdp", json={"career_goal": "Rare Role"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.headers["x-pdp-status"] == "role_profile_missing"


async def test_missing_profile_returns_422(client: httpx.AsyncClient) -> None:
    service = FakePdpService(PdpProfileMissing())
    app.dependency_overrides[get_pdp_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "s1", role="user", user_id="u1"
    )
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        response = await client.post("/api/pdp", json={"career_goal": "Data Scientist"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    assert "upload" in response.json()["detail"].lower()


async def test_generation_failed_returns_502(client: httpx.AsyncClient) -> None:
    service = FakePdpService(PdpGenerationFailed())
    app.dependency_overrides[get_pdp_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "s1", role="user", user_id="u1"
    )
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        response = await client.post("/api/pdp", json={"career_goal": "Data Scientist"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 502


async def test_over_budget_returns_429(client: httpx.AsyncClient) -> None:
    service = FakePdpService(PdpGenerated(pdf=_PDF_BYTES, pdp_id="p1", status="ok"))
    app.dependency_overrides[get_pdp_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "s1", role="user", user_id="u1"
    )
    app.dependency_overrides[get_rate_limit_service] = _capped_rate_limit_service
    try:
        response = await client.post("/api/pdp", json={"career_goal": "Data Scientist"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 429
    assert service.calls == []  # limited before the service is consulted


async def test_blank_career_goal_is_422_validation(client: httpx.AsyncClient) -> None:
    service = FakePdpService(PdpGenerated(pdf=_PDF_BYTES, pdp_id="p1", status="ok"))
    app.dependency_overrides[get_pdp_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "s1", role="user", user_id="u1"
    )
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        response = await client.post("/api/pdp", json={"career_goal": ""})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422  # FastAPI body validation (min_length=1)
    assert service.calls == []
