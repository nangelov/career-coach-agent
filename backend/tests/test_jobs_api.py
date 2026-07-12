"""API tests for ``GET /api/jobs/status/{task_id}`` (P5-06, §5.3 / §8).

Overrides :func:`~app.api.jobs.get_job_status_service` with a
:class:`~app.services.jobs.JobStatusService` over a fake ``AsyncResult`` factory, and
``require_auth`` with a stand-in :class:`~app.schemas.auth.CurrentUser`, so no real
Celery/broker/Redis wiring runs. Asserts the contract end-to-end through the router: the
progress/success/failure shapes flow through, a guest can poll (capability, not ownership), and
a missing bearer token is a ``401``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest_asyncio
from httpx import ASGITransport

from app.api.jobs import get_job_status_service
from app.main import app
from app.schemas.auth import CurrentUser
from app.security.dependencies import require_auth
from app.services.jobs import SAFE_FAILURE_MESSAGE, JobStatusService
from tests.fakes import fake_current_user


class FakeAsyncResult:
    def __init__(self, state: str, result: Any = None) -> None:
        self._state = state
        self._result = result

    @property
    def state(self) -> str:
        return self._state

    @property
    def result(self) -> Any:
        return self._result


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _wire(state: str, result: Any = None, *, user: CurrentUser | None = None) -> None:
    service = JobStatusService(lambda task_id: FakeAsyncResult(state, result))
    app.dependency_overrides[get_job_status_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: (
        user if user is not None else fake_current_user("s1", role="user", user_id="u1")
    )


async def test_in_progress_returns_stage_and_message(client: httpx.AsyncClient) -> None:
    _wire("PARSING", {"stage": "parsing", "message": "Extracting document text."})
    try:
        response = await client.get("/api/jobs/status/task-1")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == "task-1"
    assert body["status"] == "in_progress"
    assert body["state"] == "PARSING"
    assert body["stage"] == "parsing"
    assert body["message"] == "Extracting document text."


async def test_success_returns_result_payload(client: httpx.AsyncClient) -> None:
    payload = {
        "profile": {"skills": ["Python"]},
        "persisted": True,
        "kb_document_id": "doc-1",
        "chunk_count": 3,
    }
    _wire("SUCCESS", payload)
    try:
        response = await client.get("/api/jobs/status/task-2")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["result"] == payload
    assert body["error"] is None


async def test_failure_returns_safe_message(client: httpx.AsyncClient) -> None:
    _wire("FAILURE", RuntimeError("internal /path token=secret"))
    try:
        response = await client.get("/api/jobs/status/task-3")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failure"
    assert body["error"] == SAFE_FAILURE_MESSAGE
    assert "secret" not in response.text


async def test_pending_for_unknown_task(client: httpx.AsyncClient) -> None:
    _wire("PENDING", None)
    try:
        response = await client.get("/api/jobs/status/does-not-exist")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


async def test_guest_can_poll_own_job(client: httpx.AsyncClient) -> None:
    # Capability model: a guest (no user_id) polls with the token it holds — no ownership check.
    _wire("PENDING", None, user=fake_current_user("guest-s", role="guest"))
    try:
        response = await client.get("/api/jobs/status/guest-task")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


async def test_requires_auth_401(client: httpx.AsyncClient) -> None:
    # No require_auth override → the real dependency rejects the missing bearer token before the
    # service is ever consulted.
    service = JobStatusService(lambda task_id: FakeAsyncResult("PENDING", None))
    app.dependency_overrides[get_job_status_service] = lambda: service
    try:
        response = await client.get("/api/jobs/status/task-x")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401
