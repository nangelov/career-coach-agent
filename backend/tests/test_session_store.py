"""Unit tests for the session-record stores (P3-01).

Exercises the Redis adapter against a hand-rolled in-memory fake implementing the string
surface :class:`~app.repositories.redis.RedisSessionStore` uses (``set`` / ``get`` /
``delete``) — no real Redis — plus the process-local ``InMemorySessionStore``. Coverage:
create → get round trip, the TTL is applied on create, the JSON record survives a round
trip, and a missing session returns ``None``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.repositories.redis import RedisSessionStore
from app.schemas.auth import SessionRecord, SessionRole
from app.services.session_store import InMemorySessionStore


class FakeStringRedis:
    """In-memory async stand-in for the string subset of Redis the store uses.

    Stores values verbatim (``decode_responses=True`` semantics) and records the last TTL
    applied per key so tests can assert the expiry is set.
    """

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, name: str, value: Any, *, ex: int | None = None) -> bool:
        self.values[name] = str(value)
        if ex is not None:
            self.ttls[name] = ex
        return True

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            if self.values.pop(name, None) is not None:
                removed += 1
            self.ttls.pop(name, None)
        return removed


def _record(session_id: str = "sid-1", role: SessionRole = "guest") -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        role=role,
        user_id=None,
        created_at=datetime.now(UTC),
    )


# --------------------------------------------------------------------------- #
# RedisSessionStore
# --------------------------------------------------------------------------- #
async def test_create_and_get_round_trip() -> None:
    fake = FakeStringRedis()
    store = RedisSessionStore(fake)

    record = _record("sid-1")
    await store.create(record, ttl_seconds=3600)

    loaded = await store.get("sid-1")
    assert loaded is not None
    assert loaded.session_id == "sid-1"
    assert loaded.role == "guest"
    assert loaded.user_id is None


async def test_ttl_is_applied_on_create() -> None:
    fake = FakeStringRedis()
    store = RedisSessionStore(fake)

    await store.create(_record("sid-2"), ttl_seconds=1234)

    assert fake.ttls["session:record:sid-2"] == 1234


async def test_get_missing_returns_none() -> None:
    store = RedisSessionStore(FakeStringRedis())
    assert await store.get("never-seen") is None


async def test_record_is_stored_as_json() -> None:
    fake = FakeStringRedis()
    store = RedisSessionStore(fake)
    await store.create(_record("sid-3"), ttl_seconds=60)

    raw = fake.values["session:record:sid-3"]
    assert '"role":"guest"' in raw.replace(" ", "")
    assert '"session_id":"sid-3"' in raw.replace(" ", "")


async def test_ttl_floor_is_at_least_one() -> None:
    fake = FakeStringRedis()
    store = RedisSessionStore(fake)
    await store.create(_record("sid-4"), ttl_seconds=0)
    assert fake.ttls["session:record:sid-4"] == 1


# --------------------------------------------------------------------------- #
# InMemorySessionStore (test double / interim default)
# --------------------------------------------------------------------------- #
async def test_in_memory_store_round_trip() -> None:
    store = InMemorySessionStore()
    await store.create(_record("mem-1"), ttl_seconds=60)
    loaded = await store.get("mem-1")
    assert loaded is not None
    assert loaded.session_id == "mem-1"


async def test_in_memory_store_missing_returns_none() -> None:
    assert await InMemorySessionStore().get("absent") is None
