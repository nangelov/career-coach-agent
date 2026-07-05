"""Unit tests for the Redis-backed per-session memory (P1-05).

All tests run against a hand-rolled **in-memory fake** Redis implementing the list
surface :class:`~app.repositories.redis.RedisSessionMemory` uses (``rpush`` /
``lrange`` / ``ltrim`` / ``expire`` / ``delete``) — no real Redis, no network,
mirroring the fake-Redis pattern already used by ``test_llm_router.py``. Coverage
mirrors the acceptance criteria: append + load round trip, TTL is set on each append,
the history cap is enforced, two ``session_id``s are isolated, and the existing
``ChatService`` (from P1-04) works unchanged against the new memory implementation via
dependency-injection.
"""

from __future__ import annotations

from typing import Any

from app.llm.types import ChatMessage, StreamChunk
from app.repositories.redis import RedisSessionMemory
from app.schemas.chat import DoneEvent
from app.services.chat import ChatService
from tests.fakes import FakeRegistry, FakeRouter


# --------------------------------------------------------------------------- #
# Fake Redis (list surface)
# --------------------------------------------------------------------------- #
class FakeListRedis:
    """In-memory async stand-in for the list subset of Redis the store uses.

    Stores values verbatim as strings (``decode_responses=True`` semantics) and
    records the last TTL applied per key so tests can assert the expiry is set.
    """

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.ttls: dict[str, int] = {}

    async def rpush(self, name: str, *values: Any) -> int:
        target = self.lists.setdefault(name, [])
        target.extend(str(v) for v in values)
        return len(target)

    async def lrange(self, name: str, start: int, end: int) -> list[str]:
        return _slice(self.lists.get(name, []), start, end)

    async def ltrim(self, name: str, start: int, end: int) -> bool:
        if name in self.lists:
            self.lists[name] = _slice(self.lists[name], start, end)
        return True

    async def expire(self, name: str, time: int) -> bool:
        self.ttls[name] = time
        return True

    async def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            if self.lists.pop(name, None) is not None:
                removed += 1
            self.ttls.pop(name, None)
        return removed


def _slice(values: list[str], start: int, end: int) -> list[str]:
    """Redis LRANGE/LTRIM inclusive-range semantics with negative-index support."""
    n = len(values)
    if start < 0:
        start = max(n + start, 0)
    if end < 0:
        end = n + end
    if end < 0 or start >= n or start > end:
        return []
    return values[start : end + 1]


# --------------------------------------------------------------------------- #
# (a) append + load round trip
# --------------------------------------------------------------------------- #
async def test_append_and_load_round_trip() -> None:
    fake = FakeListRedis()
    memory = RedisSessionMemory(fake, ttl_seconds=3600, max_messages=100)

    messages = [
        ChatMessage(role="user", content="hello"),
        ChatMessage(role="assistant", content="hi there"),
    ]
    await memory.append("s1", messages)

    loaded = await memory.load("s1")
    assert [(m.role, m.content) for m in loaded] == [
        ("user", "hello"),
        ("assistant", "hi there"),
    ]


async def test_load_empty_session_returns_empty_list() -> None:
    memory = RedisSessionMemory(FakeListRedis())
    assert await memory.load("never-seen") == []


async def test_append_empty_is_a_noop() -> None:
    fake = FakeListRedis()
    memory = RedisSessionMemory(fake)
    await memory.append("s1", [])
    assert fake.lists == {}
    assert fake.ttls == {}


async def test_tool_call_message_round_trips_full_fidelity() -> None:
    """Assistant tool_calls and tool replies must survive JSON serialization."""
    fake = FakeListRedis()
    memory = RedisSessionMemory(fake)
    from app.llm.types import FunctionCall, ToolCall

    assistant = ChatMessage(
        role="assistant",
        content=None,
        tool_calls=[ToolCall(id="call_1", function=FunctionCall(name="search", arguments="{}"))],
    )
    tool = ChatMessage(role="tool", content='{"ok": true}', name="search", tool_call_id="call_1")
    await memory.append("s1", [assistant, tool])

    loaded = await memory.load("s1")
    assert loaded[0].tool_calls is not None
    assert loaded[0].tool_calls[0].id == "call_1"
    assert loaded[1].tool_call_id == "call_1"
    assert loaded[1].name == "search"


# --------------------------------------------------------------------------- #
# (b) TTL is set on each append
# --------------------------------------------------------------------------- #
async def test_ttl_is_set_on_append() -> None:
    fake = FakeListRedis()
    memory = RedisSessionMemory(fake, ttl_seconds=1234, max_messages=100)

    await memory.append("s1", [ChatMessage(role="user", content="hi")])

    assert fake.ttls["session:mem:s1"] == 1234


async def test_ttl_is_refreshed_on_every_append() -> None:
    fake = FakeListRedis()
    memory = RedisSessionMemory(fake, ttl_seconds=555)

    await memory.append("s1", [ChatMessage(role="user", content="a")])
    fake.ttls["session:mem:s1"] = 1  # simulate time passing / TTL decay
    await memory.append("s1", [ChatMessage(role="user", content="b")])

    assert fake.ttls["session:mem:s1"] == 555  # sliding window refreshed


# --------------------------------------------------------------------------- #
# (c) history cap enforced
# --------------------------------------------------------------------------- #
async def test_history_cap_keeps_only_most_recent() -> None:
    fake = FakeListRedis()
    memory = RedisSessionMemory(fake, max_messages=3)

    for i in range(6):
        await memory.append("s1", [ChatMessage(role="user", content=str(i))])

    loaded = await memory.load("s1")
    assert [m.content for m in loaded] == ["3", "4", "5"]


async def test_history_cap_applies_within_a_single_append() -> None:
    fake = FakeListRedis()
    memory = RedisSessionMemory(fake, max_messages=2)

    await memory.append(
        "s1",
        [ChatMessage(role="user", content=str(i)) for i in range(5)],
    )

    loaded = await memory.load("s1")
    assert [m.content for m in loaded] == ["3", "4"]


# --------------------------------------------------------------------------- #
# (d) isolation between two session ids
# --------------------------------------------------------------------------- #
async def test_two_sessions_are_isolated() -> None:
    fake = FakeListRedis()
    memory = RedisSessionMemory(fake)

    await memory.append("s1", [ChatMessage(role="user", content="from-s1")])
    await memory.append("s2", [ChatMessage(role="user", content="from-s2")])

    s1 = await memory.load("s1")
    s2 = await memory.load("s2")
    assert [m.content for m in s1] == ["from-s1"]
    assert [m.content for m in s2] == ["from-s2"]


# --------------------------------------------------------------------------- #
# (e) ChatService works unchanged against the Redis-backed memory (DI swap)
# --------------------------------------------------------------------------- #
async def test_chat_service_persists_and_replays_via_redis_memory() -> None:
    fake = FakeListRedis()
    memory = RedisSessionMemory(fake, ttl_seconds=3600, max_messages=100)
    router = FakeRouter(
        [
            [StreamChunk(content="one", finish_reason="stop")],
            [StreamChunk(content="two", finish_reason="stop")],
        ]
    )
    service = ChatService(router, FakeRegistry(), memory)  # type: ignore[arg-type]

    events1 = [e async for e in service.stream_turn("s1", "first")]
    assert any(isinstance(e, DoneEvent) for e in events1)

    events2 = [e async for e in service.stream_turn("s1", "second")]
    assert any(isinstance(e, DoneEvent) for e in events2)

    # The second model call replays the first turn (loaded back out of Redis).
    contents = [m.content for m in router.calls[1]]
    assert "first" in contents
    assert "one" in contents
    assert "second" in contents

    # And the store holds the full four-message history under the session key.
    stored = await memory.load("s1")
    assert [m.content for m in stored] == ["first", "one", "second", "two"]
