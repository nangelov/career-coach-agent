"""API tests for ``POST /api/profile/cv`` (P5-04, §5.1 / §9).

Overrides :func:`~app.api.profile.get_profile_ingest_service` with a service over a **fake
enqueuer** (records the enqueue call, returns a canned task id — no Celery/broker), plus
``require_auth`` (authenticated caller) and ``get_rate_limit_service`` (in-memory), so no real
Celery / Redis / HF wiring runs. Asserts the endpoint validates the upload, enforces the
guest upload cap, and returns ``202`` with the task id — never parsing in-request.

The real :class:`~app.services.profile_ingest.ProfileIngestService` is exercised (only its
enqueue port is faked), so the validation branches (415 unsupported / 413 too large) are
covered end-to-end through the router's exception mapping.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from httpx import ASGITransport

from app.api.profile import _read_within_cap, get_profile_ingest_service
from app.main import app
from app.security.dependencies import get_rate_limit_service, require_auth
from app.services.profile_ingest import ProfileIngestService, UploadTooLarge
from app.services.rate_limiting import InMemoryRateLimiter, RateLimitService
from tests.fakes import fake_current_user, unlimited_rate_limit_service


class _FakeEnqueuer:
    """Records the enqueue call and returns a canned task id (no broker)."""

    def __init__(self, task_id: str = "task-abc") -> None:
        self._task_id = task_id
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        *,
        content_b64: str,
        filename: str | None,
        media_type: str | None,
        user_id: str | None,
        session_id: str,
    ) -> str:
        self.calls.append(
            {
                "content_b64": content_b64,
                "filename": filename,
                "media_type": media_type,
                "user_id": user_id,
                "session_id": session_id,
            }
        )
        return self._task_id


def _service(enqueuer: _FakeEnqueuer, *, max_bytes: int = 10 * 1024 * 1024) -> ProfileIngestService:
    return ProfileIngestService(enqueuer, max_upload_bytes=max_bytes)


def _guest_upload_limited_service(limit: int = 1) -> RateLimitService:
    return RateLimitService(
        InMemoryRateLimiter(),
        guest_message_limit=10**9,
        guest_upload_limit=limit,
        guest_window_seconds=3600,
        user_message_limit=10**9,
        user_upload_limit=10**9,
        user_window_seconds=3600,
    )


async def _post_cv(
    client: httpx.AsyncClient, *, filename: str, content: bytes, content_type: str
) -> httpx.Response:
    return await client.post(
        "/api/profile/cv",
        files={"file": (filename, content, content_type)},
    )


async def test_upload_cv_enqueues_and_returns_202() -> None:
    enqueuer = _FakeEnqueuer()
    app.dependency_overrides[get_profile_ingest_service] = lambda: _service(enqueuer)
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "s1", role="user", user_id="u1"
    )
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await _post_cv(
                client, filename="cv.pdf", content=b"%PDF-1.4 fake", content_type="application/pdf"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    body = response.json()
    assert body == {"task_id": "task-abc", "status": "accepted"}
    # The task was enqueued with the caller's identity from the token, not the body.
    assert len(enqueuer.calls) == 1
    call = enqueuer.calls[0]
    assert call["user_id"] == "u1"
    assert call["session_id"] == "s1"
    assert call["filename"] == "cv.pdf"


async def test_upload_cv_rejects_unsupported_type_415() -> None:
    enqueuer = _FakeEnqueuer()
    app.dependency_overrides[get_profile_ingest_service] = lambda: _service(enqueuer)
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "s1", role="user", user_id="u1"
    )
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await _post_cv(
                client, filename="notes.txt", content=b"hello", content_type="text/plain"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 415
    assert enqueuer.calls == []  # nothing enqueued on a rejected upload


async def test_upload_cv_rejects_too_large_413() -> None:
    enqueuer = _FakeEnqueuer()
    app.dependency_overrides[get_profile_ingest_service] = lambda: _service(enqueuer, max_bytes=8)
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "s1", role="user", user_id="u1"
    )
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await _post_cv(
                client,
                filename="cv.pdf",
                content=b"%PDF-1.4 this is more than eight bytes",
                content_type="application/pdf",
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 413
    assert enqueuer.calls == []


async def test_upload_cv_guest_upload_cap_429() -> None:
    enqueuer = _FakeEnqueuer()
    limiter = _guest_upload_limited_service(limit=1)
    app.dependency_overrides[get_profile_ingest_service] = lambda: _service(enqueuer)
    app.dependency_overrides[require_auth] = lambda: fake_current_user("guest-s", role="guest")
    app.dependency_overrides[get_rate_limit_service] = lambda: limiter
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await _post_cv(
                client, filename="cv.pdf", content=b"%PDF-1.4", content_type="application/pdf"
            )
            second = await _post_cv(
                client, filename="cv.pdf", content=b"%PDF-1.4", content_type="application/pdf"
            )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 202
    assert second.status_code == 429  # guest gets exactly one upload per session
    assert len(enqueuer.calls) == 1  # the blocked upload never enqueued


class _SizeOnlyUpload:
    """UploadFile stand-in exposing ``.size`` but exploding if ``.read`` is ever called.

    Proves the pre-read size guard rejects an oversized upload *before* the body is
    materialized (C1) — if the guard fell through to reading, this blows up.
    """

    def __init__(self, size: int | None) -> None:
        self.size = size

    async def read(self, size: int = -1) -> bytes:
        raise AssertionError("read() must not be called when file.size exceeds the cap")


class _ChunkedUpload:
    """UploadFile stand-in with ``size=None`` that streams ``chunks`` — exercises the bounded
    chunked read path (the fallback guard when the size is absent/understated)."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.size: int | None = None
        self._chunks = list(chunks)

    async def read(self, size: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


async def test_read_within_cap_rejects_on_size_before_reading() -> None:
    # file.size exceeds the cap → rejected before a single byte is read (no OOM).
    with pytest.raises(UploadTooLarge):
        await _read_within_cap(_SizeOnlyUpload(size=1000), 100)  # type: ignore[arg-type]


async def test_read_within_cap_rejects_on_overflow_when_size_unknown() -> None:
    # size=None (Starlette didn't populate it) → bounded read still caps total bytes.
    upload = _ChunkedUpload([b"a" * 60, b"b" * 60])  # 120 bytes total, cap is 100
    with pytest.raises(UploadTooLarge):
        await _read_within_cap(upload, 100)  # type: ignore[arg-type]


async def test_read_within_cap_returns_body_within_cap() -> None:
    upload = _ChunkedUpload([b"hello ", b"world"])
    assert await _read_within_cap(upload, 100) == b"hello world"  # type: ignore[arg-type]


async def test_rejected_upload_does_not_consume_guest_budget() -> None:
    # C2: a guest fat-fingers an unsupported file (415); it must NOT burn their single upload,
    # so a following valid CV still succeeds (202) and is the only thing enqueued.
    enqueuer = _FakeEnqueuer()
    limiter = _guest_upload_limited_service(limit=1)
    app.dependency_overrides[get_profile_ingest_service] = lambda: _service(enqueuer)
    app.dependency_overrides[require_auth] = lambda: fake_current_user("guest-s", role="guest")
    app.dependency_overrides[get_rate_limit_service] = lambda: limiter
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            rejected = await _post_cv(
                client, filename="notes.txt", content=b"hello", content_type="text/plain"
            )
            valid = await _post_cv(
                client, filename="cv.pdf", content=b"%PDF-1.4", content_type="application/pdf"
            )
    finally:
        app.dependency_overrides.clear()

    assert rejected.status_code == 415  # bad file rejected
    assert valid.status_code == 202  # single upload still available
    assert len(enqueuer.calls) == 1  # only the valid CV was enqueued


async def test_upload_cv_requires_auth_401() -> None:
    # No require_auth override → the real dependency runs and rejects the missing bearer token.
    enqueuer = _FakeEnqueuer()
    app.dependency_overrides[get_profile_ingest_service] = lambda: _service(enqueuer)
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await _post_cv(
                client, filename="cv.pdf", content=b"%PDF-1.4", content_type="application/pdf"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert enqueuer.calls == []
