"""API tests for the ``/api/memory`` memory panel (P9-05, §5.4 / §9).

Drives the real router with a :class:`~app.services.memory.MemoryService` over an in-memory
:class:`~app.services.preferences.InMemoryPreferenceStore` and a process-local learned-memory
fake (so the full view/edit/delete flow runs without Postgres) and a stand-in authenticated
caller (``require_auth`` override). Asserts the transparency-&-control contract:

* auth is required (``401``); guests are rejected (``403`` — durable-only surface);
* view returns explicit preferences + learned memories (embeddings never present);
* view on a fresh account is an empty-but-renderable shape;
* ``PUT`` upserts preferences (immediate — no confirmation workflow);
* a user deletes their own memory (``204``); deleting another user's or an unknown id → ``404``
  (never distinguished — no ownership leak);
* ``DELETE /api/memory`` bulk-clears learned memories and leaves preferences untouched.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from app.api.memory import get_memory_service
from app.main import app
from app.repositories.vector_search import UserMemoryListItem
from app.schemas.auth import CurrentUser
from app.security.dependencies import require_auth
from app.services.memory import MemoryService
from app.services.preferences import InMemoryPreferenceStore
from tests.fakes import fake_current_user

_USER_A = "11111111-1111-1111-1111-111111111111"
_USER_B = "22222222-2222-2222-2222-222222222222"


class _FakeMemoryStore:
    """Process-local :class:`~app.services.memory.LearnedMemoryStore` — test double only.

    Keyed by ``user_id`` so delete/clear are naturally caller-scoped (a memory id belonging to
    another user is invisible to the deleting user), exactly like the Postgres primitive.
    """

    def __init__(self) -> None:
        self._by_user: dict[uuid.UUID, list[UserMemoryListItem]] = {}

    def seed(self, user_id: str, *items: UserMemoryListItem) -> None:
        self._by_user.setdefault(uuid.UUID(user_id), []).extend(items)

    async def list_memories(self, user_id: uuid.UUID) -> list[UserMemoryListItem]:
        return list(self._by_user.get(user_id, []))

    async def delete_memory_for_user(self, memory_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        items = self._by_user.get(user_id, [])
        remaining = [it for it in items if it.memory_id != memory_id]
        if len(remaining) == len(items):
            return False
        self._by_user[user_id] = remaining
        return True

    async def clear_memories(self, user_id: uuid.UUID) -> int:
        removed = len(self._by_user.get(user_id, []))
        self._by_user[user_id] = []
        return removed


def _memory(text: str, *, memory_type: str = "fact", confidence: float = 0.9) -> UserMemoryListItem:
    return UserMemoryListItem(
        memory_id=uuid.uuid4(),
        text=text,
        memory_type=memory_type,
        confidence=confidence,
        created_at=datetime.now(UTC),
    )


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def store() -> _FakeMemoryStore:
    return _FakeMemoryStore()


@pytest.fixture
def service(store: _FakeMemoryStore) -> MemoryService:
    return MemoryService(preferences=InMemoryPreferenceStore(), memories=store)


@pytest.fixture
def wire(service: MemoryService) -> Iterator[Callable[[CurrentUser], None]]:
    """Wire the in-memory-backed service once and (re)point ``require_auth`` at a caller."""
    app.dependency_overrides[get_memory_service] = lambda: service

    def _as(user: CurrentUser) -> None:
        app.dependency_overrides[require_auth] = lambda: user

    yield _as
    app.dependency_overrides.clear()


def _user(user_id: str, session_id: str = "s1") -> CurrentUser:
    return fake_current_user(session_id, role="user", user_id=user_id)


# ------------------------------------------------------------------------- auth
async def test_requires_auth_401(client: httpx.AsyncClient) -> None:
    app.dependency_overrides[get_memory_service] = lambda: MemoryService(
        preferences=InMemoryPreferenceStore(), memories=_FakeMemoryStore()
    )
    try:
        response = await client.get("/api/memory")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401


async def test_guest_rejected_403(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(fake_current_user("guest-session", role="guest"))
    response = await client.get("/api/memory")
    assert response.status_code == 403


# ------------------------------------------------------------------------- view
async def test_view_empty_for_fresh_account(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user(_USER_A))
    response = await client.get("/api/memory")
    assert response.status_code == 200
    body = response.json()
    assert body["memories"] == []
    # An empty-but-renderable preferences shape (no saved row yet).
    assert body["preferences"] == {
        "tone": None,
        "formality": None,
        "language": None,
        "focus_areas": [],
        "avoid": [],
    }


async def test_view_returns_preferences_and_memories_without_embeddings(
    client: httpx.AsyncClient, store: _FakeMemoryStore, wire: Callable[[CurrentUser], None]
) -> None:
    store.seed(_USER_A, _memory("Prefers concise answers", memory_type="style", confidence=0.8))
    wire(_user(_USER_A))
    await client.put("/api/memory/preferences", json={"tone": "encouraging", "language": "en"})

    response = await client.get("/api/memory")
    assert response.status_code == 200
    body = response.json()
    assert body["preferences"]["tone"] == "encouraging"
    assert body["preferences"]["language"] == "en"
    assert len(body["memories"]) == 1
    memory = body["memories"][0]
    assert memory["text"] == "Prefers concise answers"
    assert memory["memory_type"] == "style"
    assert memory["confidence"] == 0.8
    assert "created_at" in memory and "id" in memory
    # Embeddings never cross the wire (§7.6).
    assert "embedding" not in memory


# ------------------------------------------------------------------- preferences
async def test_put_preferences_upserts(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user(_USER_A))
    first = await client.put(
        "/api/memory/preferences",
        json={"tone": "direct", "focus_areas": ["leadership", "system design"]},
    )
    assert first.status_code == 200
    assert first.json()["focus_areas"] == ["leadership", "system design"]

    # A second PUT replaces the whole document (immediate — no confirmation).
    second = await client.put("/api/memory/preferences", json={"formality": "casual"})
    assert second.status_code == 200
    body = second.json()
    assert body["formality"] == "casual"
    assert body["tone"] is None
    assert body["focus_areas"] == []


async def test_put_preferences_rejects_overlong_item(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user(_USER_A))
    response = await client.put("/api/memory/preferences", json={"focus_areas": ["x" * 5000]})
    assert response.status_code == 422


# ----------------------------------------------------------------------- delete
async def test_delete_own_memory_204(
    client: httpx.AsyncClient, store: _FakeMemoryStore, wire: Callable[[CurrentUser], None]
) -> None:
    item = _memory("Wants to become a staff engineer")
    store.seed(_USER_A, item)
    wire(_user(_USER_A))
    response = await client.delete(f"/api/memory/{item.memory_id}")
    assert response.status_code == 204
    assert await store.list_memories(uuid.UUID(_USER_A)) == []


async def test_delete_other_users_memory_404(
    client: httpx.AsyncClient, store: _FakeMemoryStore, wire: Callable[[CurrentUser], None]
) -> None:
    item = _memory("User A's secret")
    store.seed(_USER_A, item)
    # User B tries to delete user A's memory by id.
    wire(_user(_USER_B, session_id="s2"))
    response = await client.delete(f"/api/memory/{item.memory_id}")
    assert response.status_code == 404
    # The memory still exists for its owner (not deleted, no leak).
    assert len(await store.list_memories(uuid.UUID(_USER_A))) == 1


async def test_delete_unknown_memory_404(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user(_USER_A))
    response = await client.delete(f"/api/memory/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_delete_malformed_memory_id_404(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user(_USER_A))
    response = await client.delete("/api/memory/not-a-uuid")
    assert response.status_code == 404


# ------------------------------------------------------------------------ clear
async def test_clear_memories_leaves_preferences(
    client: httpx.AsyncClient, store: _FakeMemoryStore, wire: Callable[[CurrentUser], None]
) -> None:
    store.seed(_USER_A, _memory("a"), _memory("b"))
    wire(_user(_USER_A))
    await client.put("/api/memory/preferences", json={"tone": "warm"})

    cleared = await client.delete("/api/memory")
    assert cleared.status_code == 200
    assert cleared.json()["deleted"] == 2

    # Learned memories gone, explicit preferences preserved.
    view = await client.get("/api/memory")
    assert view.json()["memories"] == []
    assert view.json()["preferences"]["tone"] == "warm"
