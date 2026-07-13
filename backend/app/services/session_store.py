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

    This store is the **authoritative registry of live sessions**: a session exists the
    moment it is created here (login/upgrade/guest), independent of any lazily-populated
    Postgres ``sessions`` row (which is only written on the first persisted chat turn). So
    "every live session belonging to a user" must be enumerated from *here*
    (:meth:`list_user_sessions`), not from Postgres — otherwise a just-logged-in device that
    has not yet chatted would be missed on erasure (SEC-05, §7.6).
    """

    @abstractmethod
    async def create(self, record: SessionRecord, *, ttl_seconds: int) -> None:
        """Persist ``record`` under its ``session_id``, expiring after ``ttl_seconds``.

        When ``record.user_id`` is set (a logged-in / upgraded session) the id is also added
        to that user's session index so :meth:`list_user_sessions` can enumerate every device.
        """

    @abstractmethod
    async def get(self, session_id: str) -> SessionRecord | None:
        """Return the stored record for ``session_id`` (``None`` if absent/expired)."""

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """Remove the record for ``session_id`` (idempotent), and drop it from its user index.

        This is what ends a session on ``POST /api/auth/logout`` (P3-02): because the
        auth dependency requires a live record to resolve the caller, deleting it revokes
        the session immediately — even while the short-lived JWT is still within its
        ``exp`` — without needing a token denylist.
        """

    @abstractmethod
    async def list_user_sessions(self, user_id: str) -> list[str]:
        """Return every live ``session_id`` belonging to ``user_id`` (empty if none).

        The authoritative "all devices" enumeration used by GDPR erasure (SEC-05) to revoke
        a user's sessions everywhere. Sourced from this store's own per-user index, so it
        includes sessions that never persisted a Postgres row. Unknown/malformed id → ``[]``.
        """


class InMemorySessionStore(SessionStore):
    """Process-local :class:`SessionStore` — test double / interim default only.

    Not for production (single-process, no restart survival, no real TTL): use
    :class:`~app.repositories.redis.RedisSessionStore` in the real app.
    """

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}
        #: user_id → its live session ids (the per-user index; mirrors the Redis set).
        self._user_index: dict[str, set[str]] = {}

    async def create(self, record: SessionRecord, *, ttl_seconds: int) -> None:
        self._records[record.session_id] = record
        if record.user_id is not None:
            self._user_index.setdefault(record.user_id, set()).add(record.session_id)

    async def get(self, session_id: str) -> SessionRecord | None:
        return self._records.get(session_id)

    async def delete(self, session_id: str) -> None:
        record = self._records.pop(session_id, None)
        if record is not None and record.user_id is not None:
            index = self._user_index.get(record.user_id)
            if index is not None:
                index.discard(session_id)
                if not index:
                    del self._user_index[record.user_id]

    async def list_user_sessions(self, user_id: str) -> list[str]:
        return list(self._user_index.get(user_id, set()))
