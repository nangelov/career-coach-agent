"""API tests for the roles surface (P6-07, §5.6 / §9).

Overrides :func:`~app.api.roles.get_roles_service` (and the auth / rate-limit deps) with fakes
so no real Postgres/Redis/Celery wiring runs. Asserts the router contract end-to-end: the
no-login ``/requirements`` route returns 200 on a hit and 202 on a cold role; ``/gap`` requires
auth, rejects guests (403), returns 200 for ok/profile_missing and 202 for an unmined role; and
an over-budget caller gets 429.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from httpx import ASGITransport

from app.api.roles import get_roles_service
from app.main import app
from app.schemas.roles import RoleRequirement, RoleRequirementsResponse
from app.schemas.skills_gap import SkillsGapResult
from app.security.dependencies import (
    get_rate_limit_service,
    require_auth,
    resolve_optional_user,
)
from app.services.rate_limiting import InMemoryRateLimiter, RateLimitService
from app.services.roles import MiningAccepted, RequirementsHit
from tests.fakes import fake_current_user, unlimited_rate_limit_service


class FakeRolesService:
    def __init__(self, *, requirements: object = None, gap: object = None) -> None:
        self._requirements = requirements
        self._gap = gap
        self.req_calls: list[str] = []
        self.gap_calls: list[tuple[str, str]] = []

    async def get_requirements(self, role: str) -> object:
        self.req_calls.append(role)
        return self._requirements

    async def get_gap(self, user_id: str, role: str) -> object:
        self.gap_calls.append((user_id, role))
        return self._gap


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


# --------------------------------------------------------------------------- #
# GET /api/roles/{role}/requirements                                          #
# --------------------------------------------------------------------------- #
async def test_requirements_cache_hit_returns_200(client: httpx.AsyncClient) -> None:
    response_body = RoleRequirementsResponse(
        role="Data Scientist",
        requirements=[RoleRequirement(skill="Python", frequency=0.9, weight=2.0, evidence=["p1"])],
        evidence_count=5,
    )
    service = FakeRolesService(requirements=RequirementsHit(response_body))
    app.dependency_overrides[get_roles_service] = lambda: service
    app.dependency_overrides[resolve_optional_user] = lambda: None  # anonymous caller, no token
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        response = await client.get("/api/roles/data%20scientist/requirements")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "Data Scientist"
    assert body["requirements"][0]["skill"] == "Python"
    assert body["requirements"][0]["evidence"] == ["p1"]


async def test_requirements_cache_miss_returns_202_with_task_id(client: httpx.AsyncClient) -> None:
    service = FakeRolesService(requirements=MiningAccepted("mine-task-1"))
    app.dependency_overrides[get_roles_service] = lambda: service
    app.dependency_overrides[resolve_optional_user] = lambda: None
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        response = await client.get("/api/roles/rare-role/requirements")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "mine-task-1"
    assert body["status"] == "accepted"


async def test_requirements_over_budget_returns_429(client: httpx.AsyncClient) -> None:
    service = FakeRolesService(requirements=MiningAccepted("never-reached"))
    app.dependency_overrides[get_roles_service] = lambda: service
    app.dependency_overrides[resolve_optional_user] = lambda: None
    app.dependency_overrides[get_rate_limit_service] = _capped_rate_limit_service
    try:
        response = await client.get("/api/roles/data-scientist/requirements")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 429
    assert service.req_calls == []  # limited before the service is consulted


# --------------------------------------------------------------------------- #
# GET /api/roles/{role}/gap                                                    #
# --------------------------------------------------------------------------- #
async def test_gap_requires_auth_401(client: httpx.AsyncClient) -> None:
    # No require_auth override → the real dependency rejects the missing bearer token.
    app.dependency_overrides[get_roles_service] = lambda: FakeRolesService()
    try:
        response = await client.get("/api/roles/data-scientist/gap")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401


async def test_gap_guest_rejected_403(client: httpx.AsyncClient) -> None:
    service = FakeRolesService(gap=SkillsGapResult(role="x", status="ok"))
    app.dependency_overrides[get_roles_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: fake_current_user("g1", role="guest")
    try:
        response = await client.get("/api/roles/data-scientist/gap")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403
    assert service.gap_calls == []  # rejected before delegating


async def test_gap_ok_returns_200(client: httpx.AsyncClient) -> None:
    result = SkillsGapResult(role="Data Scientist", status="ok", matched=["Python"], gap=[])
    service = FakeRolesService(gap=result)
    app.dependency_overrides[get_roles_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "s1", role="user", user_id="u1"
    )
    try:
        response = await client.get("/api/roles/data-scientist/gap")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["matched"] == ["Python"]
    assert service.gap_calls == [("u1", "data-scientist")]


async def test_gap_profile_missing_returns_200(client: httpx.AsyncClient) -> None:
    service = FakeRolesService(gap=SkillsGapResult(role="Data Scientist", status="profile_missing"))
    app.dependency_overrides[get_roles_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "s1", role="user", user_id="u1"
    )
    try:
        response = await client.get("/api/roles/data-scientist/gap")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "profile_missing"


async def test_gap_role_profile_missing_returns_202(client: httpx.AsyncClient) -> None:
    service = FakeRolesService(gap=MiningAccepted("gap-mine-1"))
    app.dependency_overrides[get_roles_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "s1", role="user", user_id="u1"
    )
    try:
        response = await client.get("/api/roles/data-scientist/gap")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "gap-mine-1"
    assert body["status"] == "accepted"
