"""Per-session cancel/stop signal seam (Redis-backed in :mod:`app.repositories.redis`).

The chat "stop" button (design §4 "Streaming/cancellation state"; §9
``POST /api/chat/{session}/cancel``) needs a signal an *already-streaming*
:class:`~app.services.chat.ChatService` turn can observe and act on. In v1 this was a
process-local ``active_requests`` dict — which only worked in a single process and
leaked entries. v2 replaces it with a Redis-backed flag so cancel works across
workers/processes.

This module defines the narrow interface the service depends on
(:class:`CancelRegistry`) plus a process-local implementation for tests / the P1
default. The **Redis-backed** implementation
(:class:`~app.repositories.redis.RedisCancelRegistry`) lives in the repository layer
and satisfies this same interface — services keep depending only on the port
(interface-before-implementation), and the datastore adapter lives in ``repositories/``.

.. warning::
   :class:`InMemoryCancelRegistry` keeps flags in a process-local set. It is **not**
   suitable for production (not shared across workers): a cancel issued to one worker
   would not be seen by the streaming turn on another. It exists only as the test
   double / interim default; :class:`~app.repositories.redis.RedisCancelRegistry` is the
   real store.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class CancelRegistry(ABC):
    """Set / poll / clear a per-session cancel flag.

    Implementations own storage (process-local here, Redis in the repository layer);
    callers depend only on this interface.
    """

    @abstractmethod
    async def request(self, session_id: str) -> None:
        """Request cancellation of the in-flight turn for ``session_id``."""

    @abstractmethod
    async def is_requested(self, session_id: str) -> bool:
        """Return whether a cancel has been requested for ``session_id``."""

    @abstractmethod
    async def clear(self, session_id: str) -> None:
        """Clear the cancel flag for ``session_id`` (idempotent)."""


class InMemoryCancelRegistry(CancelRegistry):
    """Process-local :class:`CancelRegistry` — interim default / test double.

    Not for production (single-process only): use
    :class:`~app.repositories.redis.RedisCancelRegistry` in the real app.
    """

    def __init__(self) -> None:
        self._requested: set[str] = set()

    async def request(self, session_id: str) -> None:
        self._requested.add(session_id)

    async def is_requested(self, session_id: str) -> bool:
        return session_id in self._requested

    async def clear(self, session_id: str) -> None:
        self._requested.discard(session_id)
