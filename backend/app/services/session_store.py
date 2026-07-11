"""Session-record store seam (Redis-backed in :mod:`app.repositories.redis`).

A guest session (P3-01) — and, in P3-02, a logged-in session — needs a small server-side
record: who the session belongs to (guest vs a user), when it started, and a TTL so
abandoned sessions self-expire (§4 ``sessions``; §7.1). This is separate from the
per-session *conversation memory* (:class:`~app.services.session_memory.SessionMemory`,
which stores turns): this store holds the **identity/lifecycle** record and is the anchor
the P3-04 guest rate-limit keys off (via ``session_id``).

Following the same interface-before-implementation idiom as ``SessionMemory`` /
``CancelRegistry``: this module defines the narrow port the auth service depends on, plus a
process-local implementation for tests / an interim default. The **Redis-backed**
implementation (:class:`~app.repositories.redis.RedisSessionStore`) lives in the repository
layer and satisfies this same port, so services keep depending only on the interface and
the datastore adapter stays in ``repositories/``.

.. warning::
   :class:`InMemorySessionStore` keeps records in a process-local dict with no real TTL
   expiry. It is **not** suitable for production (lost on restart, not shared across
   workers). It exists only as a test double / interim default;
   :class:`~app.repositories.redis.RedisSessionStore` is the real store.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.auth import SessionRecord


class SessionStore(ABC):
    """Create / fetch a server-side session record with a TTL.

    Implementations own storage (process-local here, Redis in the repository layer);
    callers depend only on this interface (interface-before-implementation).
    """

    @abstractmethod
    async def create(self, record: SessionRecord, *, ttl_seconds: int) -> None:
        """Persist ``record`` under its ``session_id``, expiring after ``ttl_seconds``."""

    @abstractmethod
    async def get(self, session_id: str) -> SessionRecord | None:
        """Return the stored record for ``session_id`` (``None`` if absent/expired)."""

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """Remove the record for ``session_id`` (idempotent).

        This is what ends a session on ``POST /api/auth/logout`` (P3-02): because the
        auth dependency requires a live record to resolve the caller, deleting it revokes
        the session immediately — even while the short-lived JWT is still within its
        ``exp`` — without needing a token denylist.
        """


class InMemorySessionStore(SessionStore):
    """Process-local :class:`SessionStore` — test double / interim default only.

    Not for production (single-process, no restart survival, no real TTL): use
    :class:`~app.repositories.redis.RedisSessionStore` in the real app.
    """

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}

    async def create(self, record: SessionRecord, *, ttl_seconds: int) -> None:
        self._records[record.session_id] = record

    async def get(self, session_id: str) -> SessionRecord | None:
        return self._records.get(session_id)

    async def delete(self, session_id: str) -> None:
        self._records.pop(session_id, None)
