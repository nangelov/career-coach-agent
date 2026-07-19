"""Unit tests for the guest personalization store (P9-07, design §5.4).

Covers the acceptance criteria for the small Redis-backed store: a round trip of
preferences + a bounded list of learned-memory strings keyed by ``session_id``; the list is
de-duplicated + capped; the TTL is refreshed on each write; and an expired key (the guest
session lapsed) reads back empty. Both the process-local test double
(:class:`~app.services.guest_memory.InMemoryGuestMemory`) and the Redis adapter
(:class:`~app.repositories.redis.RedisGuestMemory`) are exercised against a hand-rolled
in-memory fake Redis (no real Redis, no network — the fake-Redis pattern used across the suite).
"""

from __future__ import annotations

from typing import Any

from app.repositories.redis import RedisGuestMemory
from app.services.guest_memory import GuestPersonalization, InMemoryGuestMemory


# --------------------------------------------------------------------------- #
# Fake Redis (key/value surface with TTL)
# --------------------------------------------------------------------------- #
class FakeKVRedis:
    """In-memory async stand-in for the ``set(ex=)`` / ``get`` subset the store uses.

    Records the last TTL applied per key so a test can assert the expiry is set, and supports
    ``drop`` to simulate a key that has expired (its TTL lapsed).
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

    def drop(self, name: str) -> None:
        """Simulate TTL expiry: the key (and its value) is gone."""
        self.values.pop(name, None)
        self.ttls.pop(name, None)


# --------------------------------------------------------------------------- #
# InMemoryGuestMemory (test double)
# --------------------------------------------------------------------------- #
async def test_in_memory_round_trip_preferences_and_memories() -> None:
    store = InMemoryGuestMemory()

    await store.record("s1", memories=["prefers bullets"], preferences={"tone": "concise"})
    loaded = await store.load("s1")

    assert loaded.preferences == {"tone": "concise"}
    assert loaded.memories == ["prefers bullets"]


async def test_in_memory_load_absent_is_empty() -> None:
    assert await InMemoryGuestMemory().load("nope") == GuestPersonalization()


async def test_in_memory_merges_preferences_and_dedupes_memories() -> None:
    store = InMemoryGuestMemory()

    await store.record("s1", memories=["based in Berlin"], preferences={"tone": "concise"})
    # A second write merges prefs and re-observes a memory (case-insensitive dedupe → no twin).
    updated = await store.record(
        "s1", memories=["BASED IN BERLIN", "targeting PM"], preferences={"language": "en"}
    )

    assert updated.preferences == {"tone": "concise", "language": "en"}
    assert updated.memories == ["based in Berlin", "targeting PM"]


async def test_in_memory_bounds_the_memory_list() -> None:
    store = InMemoryGuestMemory(max_memories=2)

    await store.record("s1", memories=["m1", "m2", "m3"])
    loaded = await store.load("s1")

    # Oldest dropped first; only the most recent two survive.
    assert loaded.memories == ["m2", "m3"]


async def test_in_memory_load_returns_a_copy() -> None:
    store = InMemoryGuestMemory()
    await store.record("s1", memories=["m1"])

    loaded = await store.load("s1")
    loaded.memories.append("mutated")

    # Mutating the returned snapshot must not corrupt the store's state.
    assert (await store.load("s1")).memories == ["m1"]


# --------------------------------------------------------------------------- #
# RedisGuestMemory (adapter over the fake Redis)
# --------------------------------------------------------------------------- #
async def test_redis_round_trip_and_ttl_is_set() -> None:
    fake = FakeKVRedis()
    store = RedisGuestMemory(fake, ttl_seconds=3600, max_memories=50)

    await store.record("s1", memories=["prefers bullets"], preferences={"tone": "concise"})
    loaded = await store.load("s1")

    assert loaded.preferences == {"tone": "concise"}
    assert loaded.memories == ["prefers bullets"]
    # The key carries the configured TTL (sliding window, refreshed each write).
    assert fake.ttls["guest:mem:s1"] == 3600


async def test_redis_ttl_refreshed_on_each_write() -> None:
    fake = FakeKVRedis()
    store = RedisGuestMemory(fake, ttl_seconds=1200)

    await store.record("s1", memories=["m1"])
    fake.ttls["guest:mem:s1"] = 5  # pretend it aged down
    await store.record("s1", memories=["m2"])

    assert fake.ttls["guest:mem:s1"] == 1200  # refreshed back to the full TTL


async def test_redis_expired_session_reads_back_empty() -> None:
    fake = FakeKVRedis()
    store = RedisGuestMemory(fake, ttl_seconds=3600)
    await store.record("s1", memories=["ephemeral"], preferences={"tone": "concise"})

    fake.drop("guest:mem:s1")  # the guest session (and its TTL) lapsed

    assert await store.load("s1") == GuestPersonalization()


async def test_redis_dedupes_and_bounds() -> None:
    fake = FakeKVRedis()
    store = RedisGuestMemory(fake, ttl_seconds=3600, max_memories=2)

    await store.record("s1", memories=["m1", "m2"])
    await store.record("s1", memories=["M1", "m3"])  # re-observe m1 (dedupe), add m3, cap to 2
    loaded = await store.load("s1")

    assert loaded.memories == ["m2", "m3"]


async def test_redis_from_settings_uses_config() -> None:
    from app.config import settings

    store = RedisGuestMemory.from_settings(FakeKVRedis(), settings)

    # Sourced from app/config.py (the guest-session-lifetime TTL + the memory cap).
    assert store._ttl_seconds == settings.GUEST_MEMORY_TTL_SECONDS  # noqa: SLF001
    assert store._max_memories == settings.GUEST_MEMORY_MAX_MEMORIES  # noqa: SLF001
