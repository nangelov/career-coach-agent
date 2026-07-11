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
from app.schemas.auth import SessionRecord
from app.services.cancellation import CancelRegistry
from app.services.oauth_state_store import OAuthStateRecord, OAuthStateStore
from app.services.rate_limiting import RateLimiter, RateLimitResult
from app.services.session_memory import SessionMemory
from app.services.session_store import SessionStore
from app.services.upgrade_ticket_store import UpgradeTicketStore


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
class StoreRedis(Protocol):
    """The minimal async Redis surface :class:`RedisSessionStore` uses.

    A structural :class:`Protocol` (like :class:`SessionRedis` / :class:`CancelRedis`) so the
    store carries no hard driver dependency and unit tests inject an in-memory fake. The real
    ``redis.asyncio.Redis`` from the shared pool satisfies this shape.
    """

    async def set(self, name: str, value: Any, *, ex: int | None = ...) -> Any: ...
    async def get(self, name: str) -> Any: ...
    async def delete(self, *names: str) -> Any: ...


@runtime_checkable
class LimiterRedis(Protocol):
    """The minimal async Redis surface :class:`RedisRateLimiter` uses.

    A structural :class:`Protocol` (like :class:`StoreRedis` / :class:`CancelRedis`) so the
    limiter carries no hard driver dependency and unit tests inject an in-memory fake. The
    real ``redis.asyncio.Redis`` from the shared pool satisfies this shape. ``incr`` +
    ``expire`` implement a fixed-window counter; ``ttl`` gives the retry-after hint.
    """

    async def incr(self, name: str) -> Any: ...
    async def expire(self, name: str, time: int) -> Any: ...
    async def ttl(self, name: str) -> Any: ...


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


class RedisSessionStore(SessionStore):
    """Redis-backed server-side session record store (design §4 ``sessions`` / §7.1).

    Each session's :class:`~app.schemas.auth.SessionRecord` is stored as a single JSON
    string at ``<prefix>:<session_id>`` with a TTL, so an abandoned session (guest or
    logged-in) self-expires rather than lingering. This is the identity/lifecycle anchor —
    **not** conversation history (that is :class:`RedisSessionMemory`) — and the
    ``session_id`` it keys on is the same handle P3-04 uses for guest rate-limits.

    Guests live here **only** (never in Postgres ``conversations``/``messages``), per §4
    (*"Guests get NO persisted history"*): the record is anonymous (``role="guest"``,
    ``user_id=None``) and Redis-only.
    """

    def __init__(
        self,
        client: StoreRedis,
        *,
        key_prefix: str = "session:record",
    ) -> None:
        self._redis = client
        self._key_prefix = key_prefix

    @classmethod
    def from_settings(cls, client: StoreRedis, config: Settings = settings) -> RedisSessionStore:
        """Build the store (key prefix is fixed; TTL is passed per-create by the caller)."""
        return cls(client)

    def _key(self, session_id: str) -> str:
        return f"{self._key_prefix}:{session_id}"

    async def create(self, record: SessionRecord, *, ttl_seconds: int) -> None:
        """Persist ``record`` (JSON) under its session id with an expiry of ``ttl_seconds``."""
        await self._redis.set(
            self._key(record.session_id),
            record.model_dump_json(),
            ex=max(1, ttl_seconds),
        )

    async def get(self, session_id: str) -> SessionRecord | None:
        """Return the stored record for ``session_id`` (``None`` if absent/expired)."""
        raw = await self._redis.get(self._key(session_id))
        if raw is None:
            return None
        return SessionRecord.model_validate_json(raw)

    async def delete(self, session_id: str) -> None:
        """Delete the record for ``session_id`` (logout / revocation; idempotent)."""
        await self._redis.delete(self._key(session_id))


class RedisOAuthStateStore(OAuthStateStore):
    """Redis-backed pending-OIDC-transaction store (§7.1 — the login PKCE handshake).

    Each attempt's :class:`~app.services.oauth_state_store.OAuthStateRecord` is stored as a
    single JSON string at ``<prefix>:<state>`` with a short TTL, so an abandoned login (user
    closes the consent screen) self-expires. :meth:`pop` does a **get-then-delete** so a
    transaction is single-use — a replayed ``state`` cannot complete a second login.

    Uses the same narrow :class:`StoreRedis` seam as :class:`RedisSessionStore` (set/get/
    delete) — no extra driver surface.
    """

    def __init__(
        self,
        client: StoreRedis,
        *,
        key_prefix: str = "oauth:state",
    ) -> None:
        self._redis = client
        self._key_prefix = key_prefix

    @classmethod
    def from_settings(cls, client: StoreRedis, config: Settings = settings) -> RedisOAuthStateStore:
        """Build the store (key prefix is fixed; TTL is passed per-put by the caller)."""
        return cls(client)

    def _key(self, state: str) -> str:
        return f"{self._key_prefix}:{state}"

    async def put(self, state: str, record: OAuthStateRecord, *, ttl_seconds: int) -> None:
        """Persist ``record`` (JSON) under ``state`` with an expiry of ``ttl_seconds``."""
        await self._redis.set(
            self._key(state),
            record.model_dump_json(),
            ex=max(1, ttl_seconds),
        )

    async def pop(self, state: str) -> OAuthStateRecord | None:
        """Return and delete the record for ``state`` (single-use; ``None`` if absent).

        The delete is best-effort after the read; two concurrent callbacks racing the same
        ``state`` is not a practical concern (a user completes one consent), and the short
        TTL bounds any window regardless.
        """
        key = self._key(state)
        raw = await self._redis.get(key)
        if raw is None:
            return None
        await self._redis.delete(key)
        return OAuthStateRecord.model_validate_json(raw)


class RedisUpgradeTicketStore(UpgradeTicketStore):
    """Redis-backed single-use guest→account upgrade-ticket store (P3-03, §4).

    Each ticket maps its opaque id to the guest ``session_id`` it authorizes upgrading,
    stored as a single string at ``<prefix>:<ticket>`` with a short TTL so an abandoned
    upgrade self-expires. :meth:`pop` does a **get-then-delete** so a ticket is single-use —
    a replayed ticket cannot authorize a second upgrade.

    Uses the same narrow :class:`StoreRedis` seam (set/get/delete) as
    :class:`RedisSessionStore` / :class:`RedisOAuthStateStore` — no extra driver surface.
    """

    def __init__(
        self,
        client: StoreRedis,
        *,
        key_prefix: str = "upgrade:ticket",
    ) -> None:
        self._redis = client
        self._key_prefix = key_prefix

    @classmethod
    def from_settings(
        cls, client: StoreRedis, config: Settings = settings
    ) -> RedisUpgradeTicketStore:
        """Build the store (key prefix is fixed; TTL is passed per-put by the caller)."""
        return cls(client)

    def _key(self, ticket: str) -> str:
        return f"{self._key_prefix}:{ticket}"

    async def put(self, ticket: str, guest_session_id: str, *, ttl_seconds: int) -> None:
        """Persist ``guest_session_id`` under ``ticket`` with an expiry of ``ttl_seconds``."""
        await self._redis.set(self._key(ticket), guest_session_id, ex=max(1, ttl_seconds))

    async def pop(self, ticket: str) -> str | None:
        """Return and delete the guest session id for ``ticket`` (single-use, ``None`` if gone)."""
        key = self._key(ticket)
        value = await self._redis.get(key)
        if value is None:
            return None
        await self._redis.delete(key)
        return str(value)


class RedisRateLimiter(RateLimiter):
    """Redis-backed fixed-window rate-limit counter (design §6.8 / §7).

    Implements the :class:`~app.services.rate_limiting.RateLimiter` port with the classic
    ``INCR`` + first-hit ``EXPIRE`` fixed-window counter: the counter at ``<prefix>:<key>`` is
    incremented atomically per action and given a TTL of ``window_seconds`` on its **first**
    hit, so the budget resets once the window lapses (and an abandoned guest's counters
    self-clean). This is what enforces the guest 10-message / 1-upload cap and the generous
    per-user limits, keyed on the identity established at login (P3-01/P3-02).

    Uses the narrow :class:`LimiterRedis` seam (``incr`` / ``expire`` / ``ttl``) — no extra
    driver surface. Setting the expiry only on the first hit (``count == 1``) keeps the window
    *fixed* (not sliding), so a continuously-active user's window still resets on schedule.

    .. note::
       ``INCR`` then ``EXPIRE`` are two commands, not one transaction: a process crash between
       them could leave a counter without a TTL (a permanent, namespaced key for that
       session/user). The window is short and the key self-namespaced, so the practical impact
       is negligible; a Lua/pipeline atomic variant is a possible future hardening.
    """

    def __init__(
        self,
        client: LimiterRedis,
        *,
        key_prefix: str = "ratelimit",
    ) -> None:
        self._redis = client
        self._key_prefix = key_prefix

    @classmethod
    def from_settings(cls, client: LimiterRedis, config: Settings = settings) -> RedisRateLimiter:
        """Build the limiter (key prefix is fixed; limits/windows are passed per-hit)."""
        return cls(client)

    def _key(self, key: str) -> str:
        return f"{self._key_prefix}:{key}"

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        """Increment the fixed-window counter for ``key`` and report the budget status."""
        full_key = self._key(key)
        count = int(await self._redis.incr(full_key))
        if count == 1:
            # First hit of a window: stamp the expiry so the budget resets after the window.
            await self._redis.expire(full_key, max(1, window_seconds))
        allowed = count <= limit
        retry_after: int | None = None
        if not allowed:
            ttl = int(await self._redis.ttl(full_key))
            # ttl < 0 means "no expiry set" (the crash window above) — fall back to the window.
            retry_after = ttl if ttl > 0 else window_seconds
        return RateLimitResult(
            allowed=allowed, count=count, limit=limit, retry_after_seconds=retry_after
        )


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
