"""API tests for the ``/api/dashboard`` surface (P8-02, §5.2 / §9).

Overrides :func:`~app.api.dashboard.get_dashboard_service` with a real
:class:`~app.services.dashboard.DashboardService` over an
:class:`~app.services.dashboard_store.InMemoryDashboardStore` (so the full CRUD/summary flow runs
without Postgres) and ``require_auth`` with a stand-in caller. Asserts the router contract:
auth is required (401), guests are rejected (403), CRUD round-trips, cross-user access is a 404,
every write is stamped ``source="user"``, and the summary endpoint shape.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from app.api.dashboard import get_dashboard_service
from app.main import app
from app.schemas.auth import CurrentUser
from app.security.dependencies import require_auth
from app.services.dashboard import DashboardService
from app.services.dashboard_store import InMemoryDashboardStore
from tests.fakes import fake_current_user


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def service() -> DashboardService:
    return DashboardService(InMemoryDashboardStore())


@pytest.fixture
def wire(service: DashboardService) -> Iterator[Callable[[CurrentUser], None]]:
    """Wire the in-memory-backed service once and (re)point ``require_auth`` at a caller."""
    app.dependency_overrides[get_dashboard_service] = lambda: service

    def _as(user: CurrentUser) -> None:
        app.dependency_overrides[require_auth] = lambda: user

    yield _as
    app.dependency_overrides.clear()


def _user(user_id: str, session_id: str = "s1") -> CurrentUser:
    return fake_current_user(session_id, role="user", user_id=user_id)


# ------------------------------------------------------------------------- auth
async def test_requires_auth_401(client: httpx.AsyncClient) -> None:
    app.dependency_overrides[get_dashboard_service] = lambda: DashboardService(
        InMemoryDashboardStore()
    )
    try:
        response = await client.get("/api/dashboard")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401


async def test_guest_rejected_403(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(fake_current_user("guest-s", role="guest"))
    # A representative sample of the surface: read, create, and summary all reject a guest.
    assert (await client.get("/api/dashboard")).status_code == 403
    assert (await client.get("/api/dashboard/goals")).status_code == 403
    created = await client.post("/api/dashboard/goals", json={"title": "G"})
    assert created.status_code == 403


# ------------------------------------------------------------------------- goals
async def test_create_and_get_goal(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user("u1"))
    created = await client.post(
        "/api/dashboard/goals",
        json={"title": "Become Staff Engineer", "target_role": "Staff Engineer"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["title"] == "Become Staff Engineer"
    assert body["status"] == "active"
    assert body["source"] == "user"  # human write is always attributed to the user

    got = await client.get(f"/api/dashboard/goals/{body['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == body["id"]


async def test_patch_and_delete_goal(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user("u1"))
    goal_id = (await client.post("/api/dashboard/goals", json={"title": "G"})).json()["id"]

    patched = await client.patch(f"/api/dashboard/goals/{goal_id}", json={"status": "completed"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "completed"

    deleted = await client.delete(f"/api/dashboard/goals/{goal_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/dashboard/goals/{goal_id}")).status_code == 404


async def test_patch_rejects_proposed_status_422(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    # 'proposed' is reserved for AI writes — the human API schema rejects it (422 validation).
    wire(_user("u1"))
    goal_id = (await client.post("/api/dashboard/goals", json={"title": "G"})).json()["id"]
    response = await client.patch(f"/api/dashboard/goals/{goal_id}", json={"status": "proposed"})
    assert response.status_code == 422


async def test_cross_user_goal_is_404(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user("A", session_id="sa"))
    goal_id = (await client.post("/api/dashboard/goals", json={"title": "A-secret"})).json()["id"]

    wire(_user("B", session_id="sb"))
    assert (await client.get(f"/api/dashboard/goals/{goal_id}")).status_code == 404
    assert (await client.get("/api/dashboard/goals")).json() == []
    assert (
        await client.patch(f"/api/dashboard/goals/{goal_id}", json={"title": "x"})
    ).status_code == 404
    assert (await client.delete(f"/api/dashboard/goals/{goal_id}")).status_code == 404


# ------------------------------------------------------------------- milestones/tasks
async def test_milestone_and_task_crud(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user("u1"))
    goal_id = (await client.post("/api/dashboard/goals", json={"title": "G"})).json()["id"]

    milestone = await client.post(
        f"/api/dashboard/goals/{goal_id}/milestones", json={"title": "M1"}
    )
    assert milestone.status_code == 201
    assert milestone.json()["goal_id"] == goal_id

    listed = await client.get(f"/api/dashboard/goals/{goal_id}/milestones")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    task = await client.post(
        "/api/dashboard/tasks",
        json={"goal_id": goal_id, "title": "T1", "milestone_id": milestone.json()["id"]},
    )
    assert task.status_code == 201
    assert task.json()["source"] == "user"

    tasks = await client.get("/api/dashboard/tasks", params={"goal_id": goal_id})
    assert [t["title"] for t in tasks.json()] == ["T1"]


async def test_task_for_unknown_goal_is_404(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user("u1"))
    response = await client.post(
        "/api/dashboard/tasks",
        json={"goal_id": "00000000-0000-0000-0000-000000000000", "title": "T"},
    )
    assert response.status_code == 404


# ------------------------------------------------------------------------- progress
async def test_progress_post_and_list(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user("u1"))
    entry = await client.post("/api/dashboard/progress", json={"note": "made progress"})
    assert entry.status_code == 201
    assert entry.json()["source"] == "user"

    listed = await client.get("/api/dashboard/progress")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


async def test_progress_bad_reference_is_404(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user("u1"))
    response = await client.post(
        "/api/dashboard/progress",
        json={"goal_id": "00000000-0000-0000-0000-000000000000", "note": "x"},
    )
    assert response.status_code == 404


# -------------------------------------------------------------------------- summary
async def test_summary_shape(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user("u1"))
    goal_id = (await client.post("/api/dashboard/goals", json={"title": "G"})).json()["id"]
    await client.post(f"/api/dashboard/goals/{goal_id}/milestones", json={"title": "M"})
    await client.post("/api/dashboard/tasks", json={"goal_id": goal_id, "title": "T"})
    await client.post("/api/dashboard/progress", json={"note": "n"})

    summary = await client.get("/api/dashboard")
    assert summary.status_code == 200
    body = summary.json()
    assert len(body["goals"]) == 1
    goal = body["goals"][0]
    assert len(goal["milestones"]) == 1
    assert len(goal["tasks"]) == 1
    assert "time_progress_pct" in goal
    assert "task_completion_pct" in goal
    assert body["progress"]["total_entries"] == 1
    assert body["progress"]["current_streak_days"] == 1
