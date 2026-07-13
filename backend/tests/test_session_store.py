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
        self.sets: dict[str, set[str]] = {}

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

    async def sadd(self, name: str, *values: Any) -> int:
        members = self.sets.setdefault(name, set())
        added = 0
        for value in values:
            if str(value) not in members:
                members.add(str(value))
                added += 1
        return added

    async def srem(self, name: str, *values: Any) -> int:
        members = self.sets.get(name, set())
        removed = 0
        for value in values:
            if str(value) in members:
                members.discard(str(value))
                removed += 1
        if not members:
            self.sets.pop(name, None)
        return removed

    async def smembers(self, name: str) -> set[str]:
        return set(self.sets.get(name, set()))

    async def expire(self, name: str, time: int) -> bool:
        if name in self.sets or name in self.values:
            self.ttls[name] = time
            return True
        return False


def _record(session_id: str = "sid-1", role: SessionRole = "guest") -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        role=role,
        user_id=None,
        created_at=datetime.now(UTC),
    )


def _user_record(session_id: str, user_id: str) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        role="user",
        user_id=user_id,
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
# Per-user session index (SEC-05) — the authoritative "all devices" enumeration
# --------------------------------------------------------------------------- #
async def test_user_sessions_are_indexed_and_enumerable() -> None:
    fake = FakeStringRedis()
    store = RedisSessionStore(fake)
    # Two devices for the same user; the index must hold both (independent of any
    # Postgres row — this is the login-shaped case the erasure fix relies on).
    await store.create(_user_record("s1", "u1"), ttl_seconds=3600)
    await store.create(_user_record("s2", "u1"), ttl_seconds=3600)

    assert sorted(await store.list_user_sessions("u1")) == ["s1", "s2"]
    # The index set is TTL'd so it self-cleans with the sessions it tracks.
    assert fake.ttls["session:user:u1"] == 3600


async def test_guest_sessions_are_not_indexed() -> None:
    fake = FakeStringRedis()
    store = RedisSessionStore(fake)
    await store.create(_record("guest-1"), ttl_seconds=3600)
    # A guest (user_id=None) has no user index entry.
    assert fake.sets == {}


async def test_list_user_sessions_empty_for_unknown_user() -> None:
    store = RedisSessionStore(FakeStringRedis())
    assert await store.list_user_sessions("nobody") == []


async def test_delete_removes_session_from_user_index() -> None:
    fake = FakeStringRedis()
    store = RedisSessionStore(fake)
    await store.create(_user_record("s1", "u1"), ttl_seconds=3600)
    await store.create(_user_record("s2", "u1"), ttl_seconds=3600)

    await store.delete("s1")

    # The record is gone and the index no longer lists the revoked session.
    assert await store.get("s1") is None
    assert await store.list_user_sessions("u1") == ["s2"]


async def test_erasure_revokes_every_indexed_session() -> None:
    fake = FakeStringRedis()
    store = RedisSessionStore(fake)
    await store.create(_user_record("s1", "u1"), ttl_seconds=3600)
    await store.create(_user_record("s2", "u1"), ttl_seconds=3600)

    # Enumerate every device from the index, then revoke each (the erase path's shape).
    for session_id in await store.list_user_sessions("u1"):
        await store.delete(session_id)

    assert await store.get("s1") is None
    assert await store.get("s2") is None
    assert await store.list_user_sessions("u1") == []


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


async def test_in_memory_store_indexes_and_revokes_user_sessions() -> None:
    store = InMemorySessionStore()
    await store.create(_user_record("s1", "u1"), ttl_seconds=60)
    await store.create(_user_record("s2", "u1"), ttl_seconds=60)
    await store.create(_record("guest-1"), ttl_seconds=60)  # not indexed (user_id=None)

    assert sorted(await store.list_user_sessions("u1")) == ["s1", "s2"]

    await store.delete("s1")
    assert await store.list_user_sessions("u1") == ["s2"]
