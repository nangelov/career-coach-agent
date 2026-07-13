"""Unit tests for the Tavily 3-key rotating search pool (P6-03, §5.7 / §6.19).

Covers: normalization of the Tavily response, in-call failover across keys,
promote-the-survivor-to-primary persisted in the (fake) Redis, cross-call use of the
promoted primary, per-key circuit-breaking (reusing ``llm/router``'s ``CircuitBreaker``),
Redis result caching, and the not-configured / exhausted error paths. All HTTP is
served by an ``httpx.MockTransport`` keyed on the ``Authorization`` header — no real
network, and the raw key never appears in a circuit-breaker key.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.tools.tavily_pool import (
    CIRCUIT_KEY_PREFIX,
    PRIMARY_INDEX_KEY,
    TavilyNotConfiguredError,
    TavilyPool,
    TavilyPoolExhaustedError,
)


class FakeRedis:
    """In-memory async stand-in for the ``RedisLike`` subset the pool uses (TTLs ignored)."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def get(self, name: str) -> Any:
        return self.store.get(name)

    async def set(self, name: str, value: Any, *, ex: int | None = None) -> Any:
        self.store[name] = value
        return True

    async def incr(self, name: str) -> int:
        value = int(self.store.get(name, 0)) + 1
        self.store[name] = value
        return value

    async def expire(self, name: str, time: int) -> Any:
        return True

    async def delete(self, *names: str) -> Any:
        for name in names:
            self.store.pop(name, None)
        return len(names)


def _ok(title: str = "t", url: str = "https://example.com", content: str = "c") -> dict[str, Any]:
    return {"results": [{"title": title, "url": url, "content": content}]}


def _keyed_client(
    behaviors: dict[str, Callable[[httpx.Request], httpx.Response]],
    counter: dict[str, int] | None = None,
) -> httpx.AsyncClient:
    """Build a mock-transport client that dispatches on the bearer key value."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers.get("authorization", "").removeprefix("Bearer ")
        if counter is not None:
            counter[key] = counter.get(key, 0) + 1
        return behaviors[key](request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_search_normalizes_results() -> None:
    client = _keyed_client({"k1": lambda r: httpx.Response(200, json=_ok(content="hello"))})
    pool = TavilyPool(["k1"], http_client=client)

    results = await pool.search("query", 5)

    assert results == [{"title": "t", "url": "https://example.com", "snippet": "hello"}]


async def test_not_configured_raises() -> None:
    pool = TavilyPool([])
    assert not pool.is_configured
    with pytest.raises(TavilyNotConfiguredError):
        await pool.search("q", 5)


async def test_all_keys_fail_raises_exhausted() -> None:
    client = _keyed_client(
        {
            "k1": lambda r: httpx.Response(503),
            "k2": lambda r: httpx.Response(429),
        }
    )
    pool = TavilyPool(["k1", "k2"], http_client=client, redis_client=FakeRedis())
    with pytest.raises(TavilyPoolExhaustedError):
        await pool.search("q", 5)


async def test_failover_promotes_survivor_to_primary() -> None:
    redis = FakeRedis()
    counter: dict[str, int] = {}
    client = _keyed_client(
        {
            "k1": lambda r: httpx.Response(503),
            "k2": lambda r: httpx.Response(200, json=_ok(content="from-k2")),
        },
        counter=counter,
    )
    pool = TavilyPool(["k1", "k2"], http_client=client, redis_client=redis)

    results = await pool.search("q", 5)

    assert results[0]["snippet"] == "from-k2"
    # k1 tried once (failed), k2 tried once (succeeded), and k2 (index 1) is now primary.
    assert counter == {"k1": 1, "k2": 1}
    assert redis.store[PRIMARY_INDEX_KEY] == "1"
    # k1's circuit-breaker state is keyed on the index, never the raw secret.
    assert any(k.startswith(f"{CIRCUIT_KEY_PREFIX}:0") for k in redis.store)
    assert not any("k1" in k for k in redis.store)


async def test_promoted_primary_is_tried_first_on_next_call() -> None:
    redis = FakeRedis()
    redis.store[PRIMARY_INDEX_KEY] = "1"  # k2 was promoted earlier
    counter: dict[str, int] = {}
    client = _keyed_client(
        {
            "k1": lambda r: httpx.Response(503),
            "k2": lambda r: httpx.Response(200, json=_ok(content="from-k2")),
        },
        counter=counter,
    )
    pool = TavilyPool(["k1", "k2"], http_client=client, redis_client=redis)

    results = await pool.search("fresh query", 5)

    # Starts at the promoted primary (k2) and never touches the dead k1.
    assert results[0]["snippet"] == "from-k2"
    assert counter == {"k2": 1}


async def test_open_circuit_skips_key() -> None:
    redis = FakeRedis()
    # Pre-open key index 0's circuit (as the breaker would after repeated failures).
    redis.store[f"{CIRCUIT_KEY_PREFIX}:0:open"] = "1"
    counter: dict[str, int] = {}
    client = _keyed_client(
        {
            "k1": lambda r: httpx.Response(200, json=_ok(content="from-k1")),
            "k2": lambda r: httpx.Response(200, json=_ok(content="from-k2")),
        },
        counter=counter,
    )
    pool = TavilyPool(["k1", "k2"], http_client=client, redis_client=redis)

    results = await pool.search("q", 5)

    # k1 is skipped (circuit open); k2 serves it.
    assert results[0]["snippet"] == "from-k2"
    assert counter == {"k2": 1}


async def test_result_is_cached_and_reused() -> None:
    redis = FakeRedis()
    counter: dict[str, int] = {}
    client = _keyed_client(
        {"k1": lambda r: httpx.Response(200, json=_ok(content="cached"))},
        counter=counter,
    )
    pool = TavilyPool(["k1"], http_client=client, redis_client=redis)

    first = await pool.search("Same Query", 5)
    # A second identical query (normalization ignores case/whitespace) hits the cache.
    second = await pool.search("  same   query  ", 5)

    assert first == second == [{"title": "t", "url": "https://example.com", "snippet": "cached"}]
    assert counter == {"k1": 1}  # network hit only once


async def test_no_redis_still_fails_over_in_call() -> None:
    counter: dict[str, int] = {}
    client = _keyed_client(
        {
            "k1": lambda r: httpx.Response(503),
            "k2": lambda r: httpx.Response(200, json=_ok(content="from-k2")),
        },
        counter=counter,
    )
    # No redis_client: in-call failover still works; promotion/cache are simply no-ops.
    pool = TavilyPool(["k1", "k2"], http_client=client)

    results = await pool.search("q", 5)

    assert results[0]["snippet"] == "from-k2"
    assert counter == {"k1": 1, "k2": 1}
