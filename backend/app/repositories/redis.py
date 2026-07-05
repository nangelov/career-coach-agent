"""Redis repository layer — the single shared connection pool + session memory (§4).

Two things live here, both in the **repository** layer so services never touch a
datastore driver directly:

* :class:`RedisConnectionProvider` — owns the one shared ``redis.asyncio``
  :class:`~redis.asyncio.ConnectionPool` (**max 10 connections**, design §4). Every
  request/agent that needs Redis (this task's session memory, P1-02's router
  circuit-breaker, future rate-limiting/caching) acquires a client from *this* pool.
  Per the design: "Do not instantiate per-request ``Redis()`` clients; acquire via
  the repository layer only."
* :class:`RedisSessionMemory` — the Redis-backed :class:`SessionMemory` that replaces
  P1-04's interim process-local ``InMemorySessionMemory``. It is the v1→v2 fix for the
  global module-level ``ConversationBufferMemory``: history is now **per-session,
  TTL'd, and bounded**, with no shared global state across requests.
* :class:`RedisCancelRegistry` — the Redis-backed stop/cancel signal (§4:
  "Streaming/cancellation state — replaces v1's in-process ``active_requests`` dict").
  ``POST /api/chat/{session}/cancel`` sets a short-lived flag for a ``session_id``; the
  in-flight :class:`~app.services.chat.ChatService` loop polls it and ends the stream
  cleanly. Redis-backed (not a module dict) so cancel works across workers/processes.

The :class:`SessionMemory` ABC (the port the chat service depends on) stays in
:mod:`app.services.session_memory`; this module provides the Redis *adapter*
implementing it — services keep depending only on the ABC (interface-before-
implementation), and the concrete store lives in ``repositories/`` per §8.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from redis.asyncio import ConnectionPool, Redis

from app.config import Settings, settings
from app.llm.types import ChatMessage
from app.services.cancellation import CancelRegistry
from app.services.session_memory import SessionMemory


@runtime_checkable
class SessionRedis(Protocol):
    """The minimal async Redis surface :class:`RedisSessionMemory` uses.

    Kept as a structural :class:`Protocol` (mirroring the router's ``RedisLike``) so
    the store carries no hard driver dependency in its type surface and unit tests can
    inject an in-memory fake. The real ``redis.asyncio.Redis`` — acquired from the
    shared pool — satisfies this shape.
    """

    async def rpush(self, name: str, *values: Any) -> Any: ...
    async def lrange(self, name: str, start: int, end: int) -> Any: ...
    async def ltrim(self, name: str, start: int, end: int) -> Any: ...
    async def expire(self, name: str, time: int) -> Any: ...
    async def delete(self, *names: str) -> Any: ...


@runtime_checkable
class CancelRedis(Protocol):
    """The minimal async Redis surface :class:`RedisCancelRegistry` uses.

    A structural :class:`Protocol` (like :class:`SessionRedis`) so the registry carries
    no hard driver dependency and unit tests inject an in-memory fake. The real
    ``redis.asyncio.Redis`` from the shared pool satisfies this shape.
    """

    async def set(self, name: str, value: Any, *, ex: int | None = ...) -> Any: ...
    async def exists(self, *names: str) -> Any: ...
    async def delete(self, *names: str) -> Any: ...


class RedisConnectionProvider:
    """Owns the single shared ``redis.asyncio`` connection pool (design §4).

    Build once at the composition root and share the same :meth:`client` everywhere
    that needs Redis. Handing out clients that all wrap the *one* pool (rather than
    calling ``Redis.from_url`` per feature) is what enforces the "max 10 connections,
    one pool" rule — a :class:`~redis.asyncio.Redis` created from a pool is a cheap
    handle, not a new connection set.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool
        self._client: Redis | None = None

    @classmethod
    def from_settings(cls, config: Settings = settings) -> RedisConnectionProvider:
        """Create the shared pool from ``REDIS_URL`` (lazy — no I/O until first command)."""
        pool: ConnectionPool = ConnectionPool.from_url(
            config.REDIS_URL,
            max_connections=config.REDIS_MAX_CONNECTIONS,
            encoding="utf-8",
            decode_responses=True,
        )
        return cls(pool)

    @property
    def pool(self) -> ConnectionPool:
        return self._pool

    def client(self) -> Redis:
        """Return the shared :class:`~redis.asyncio.Redis` bound to the pool.

        The same client instance is reused for the life of the provider; all callers
        share it (and therefore the one bounded pool).
        """
        if self._client is None:
            self._client = Redis(connection_pool=self._pool)
        return self._client

    async def aclose(self) -> None:
        """Close the shared client and disconnect the pool (best-effort teardown)."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        await self._pool.disconnect()


class RedisSessionMemory(SessionMemory):
    """Redis-backed per-session conversation memory (design §4).

    Each session's turns are stored as a Redis **list** at ``<prefix>:<session_id>``,
    one JSON-serialised :class:`~app.llm.types.ChatMessage` per element. This replaces
    the interim process-local store: history is now isolated per ``session_id``,
    survives across workers/processes, and cannot grow without bound.

    * **TTL** — every :meth:`append` refreshes the key's expiry to
      ``ttl_seconds`` (a *sliding* window): an actively-used session stays warm, an
      idle one lapses (default 24h). Applies to guest and logged-in sessions alike at
      this phase (durable Postgres history for logged-in users is P2).
    * **Bounded** — after appending, the list is trimmed to the last
      ``max_messages`` elements (oldest dropped first) so a long-lived session_id's
      Redis footprint stays bounded (recent turns only, §4).

    .. note::
       The trim is a simple count cap. For a very long conversation (> ``max_messages``)
       the boundary could drop a ``role="tool"`` message while keeping later turns; this
       matches the interim store's naive cap and is acceptable for P1. A turn-aware cap
       (never splitting an assistant tool-call / tool-result pair) is a future refinement.
    """

    def __init__(
        self,
        client: SessionRedis,
        *,
        ttl_seconds: int = 86_400,
        max_messages: int = 100,
        key_prefix: str = "session:mem",
    ) -> None:
        self._redis = client
        self._ttl_seconds = ttl_seconds
        self._max_messages = max(1, max_messages)
        self._key_prefix = key_prefix

    @classmethod
    def from_settings(cls, client: SessionRedis, config: Settings = settings) -> RedisSessionMemory:
        """Build from application config (TTL + cap sourced from ``app/config.py``)."""
        return cls(
            client,
            ttl_seconds=config.SESSION_MEMORY_TTL_SECONDS,
            max_messages=config.SESSION_MEMORY_MAX_MESSAGES,
        )

    def _key(self, session_id: str) -> str:
        return f"{self._key_prefix}:{session_id}"

    async def load(self, session_id: str) -> list[ChatMessage]:
        """Return the stored messages for ``session_id`` (empty list if none)."""
        raw = await self._redis.lrange(self._key(session_id), 0, -1)
        return [ChatMessage.model_validate_json(item) for item in raw]

    async def append(self, session_id: str, messages: Sequence[ChatMessage]) -> None:
        """Append ``messages`` in order, then enforce the cap and refresh the TTL."""
        payloads = [message.model_dump_json() for message in messages]
        if not payloads:
            return
        key = self._key(session_id)
        await self._redis.rpush(key, *payloads)
        # Keep only the most recent ``max_messages`` elements (oldest trimmed first).
        await self._redis.ltrim(key, -self._max_messages, -1)
        # Sliding TTL: refreshed on each turn so active sessions persist (§4).
        await self._redis.expire(key, self._ttl_seconds)


class RedisCancelRegistry(CancelRegistry):
    """Redis-backed stop/cancel signal for in-flight chat streams (design §4).

    Replaces v1's in-process ``active_requests`` module dict (which only worked in a
    single process and leaked entries). ``POST /api/chat/{session}/cancel`` calls
    :meth:`request` to set a flag at ``<prefix>:<session_id>``; the in-flight
    :class:`~app.services.chat.ChatService` loop polls :meth:`is_requested` at its
    checkpoints and, when set, stops and emits a terminal ``cancelled`` event.

    Leak safety (three layers, so a stale flag never wrongly cancels a *future*
    request on the same ``session_id``):

    * **Short TTL** — the flag self-expires (``ttl_seconds``, default 60s) if no
      in-flight stream ever observes it (e.g. cancel raced a just-finished turn).
    * **Observed → cleared** — the loop deletes the flag the moment it acts on it.
    * **Fresh turn clears** — :class:`ChatService` drops any stale flag at the start
      of every new turn, so a turn is never born cancelled.

    No auth/ownership yet (P3): anyone who knows a ``session_id`` can cancel it. That
    gap is closed by the P3 AuthZ task (per-session/user access control + rate limits).
    """

    def __init__(
        self,
        client: CancelRedis,
        *,
        ttl_seconds: int = 60,
        key_prefix: str = "session:cancel",
    ) -> None:
        self._redis = client
        self._ttl_seconds = max(1, ttl_seconds)
        self._key_prefix = key_prefix

    @classmethod
    def from_settings(cls, client: CancelRedis, config: Settings = settings) -> RedisCancelRegistry:
        """Build from application config (TTL sourced from ``app/config.py``)."""
        return cls(client, ttl_seconds=config.CHAT_CANCEL_TTL_SECONDS)

    def _key(self, session_id: str) -> str:
        return f"{self._key_prefix}:{session_id}"

    async def request(self, session_id: str) -> None:
        """Set the cancel flag for ``session_id`` (short TTL as a leak backstop)."""
        await self._redis.set(self._key(session_id), "1", ex=self._ttl_seconds)

    async def is_requested(self, session_id: str) -> bool:
        """Return whether a cancel has been requested for ``session_id``."""
        return bool(await self._redis.exists(self._key(session_id)))

    async def clear(self, session_id: str) -> None:
        """Delete the cancel flag for ``session_id`` (idempotent)."""
        await self._redis.delete(self._key(session_id))
