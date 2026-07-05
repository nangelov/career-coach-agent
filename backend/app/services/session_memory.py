"""Per-session conversation memory seam (interim; Redis-backed in P1-05).

The chat service needs the prior turns of a conversation to give the model
context. The **persistent, Redis-backed** implementation is the next task (P1-05);
this module defines the narrow interface the endpoint depends on now, plus a
process-local implementation good enough for the P1 walking skeleton.

The seam is deliberately tiny — :meth:`SessionMemory.load` /
:meth:`SessionMemory.append` — so P1-05 can drop a Redis-backed store in behind the
**same** interface without changing the ``POST /api/chat`` public contract or the
service's loop.

.. warning::
   :class:`InMemorySessionMemory` keeps history in a plain process-local dict. It is
   **not** suitable for production (lost on restart, not shared across workers, grows
   unbounded). It exists only so the walking skeleton can be exercised end-to-end
   until P1-05 wires the Redis-backed store.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from app.llm.types import ChatMessage


class SessionMemory(ABC):
    """Load/append the message history for a chat session.

    Implementations own storage (process-local now, Redis in P1-05); callers depend
    only on this interface (interface-before-implementation).
    """

    @abstractmethod
    async def load(self, session_id: str) -> list[ChatMessage]:
        """Return the stored messages for ``session_id`` (empty list if none)."""

    @abstractmethod
    async def append(self, session_id: str, messages: Sequence[ChatMessage]) -> None:
        """Append ``messages`` to ``session_id``'s history, in order."""

    async def get_message(self, session_id: str, message_id: str) -> ChatMessage | None:
        """Return the stored assistant message stamped with ``message_id``, or ``None``.

        The plumbing the future feedback surface keys off — design §5.5 ("each assistant
        message carries a stable ``message_id``"), consumed by the ``message_feedback``
        table (P2) and ``POST /api/messages/{message_id}/feedback`` (P9). Implemented once
        on the ABC over :meth:`load` (a scan of a bounded, recent-turns history), so every
        implementation gains lookup-by-id **without a schema change**. Not full feedback
        storage — just recoverability of the message the user reacted to.
        """
        for message in await self.load(session_id):
            if message.message_id == message_id:
                return message
        return None


class InMemorySessionMemory(SessionMemory):
    """Process-local :class:`SessionMemory` — interim, replaced by Redis in P1-05.

    An optional ``max_messages`` cap keeps a single session's history from growing
    without bound within a process; the oldest messages are dropped first.
    """

    def __init__(self, *, max_messages: int | None = 100) -> None:
        self._store: dict[str, list[ChatMessage]] = {}
        self._max_messages = max_messages

    async def load(self, session_id: str) -> list[ChatMessage]:
        return list(self._store.get(session_id, []))

    async def append(self, session_id: str, messages: Sequence[ChatMessage]) -> None:
        history = self._store.setdefault(session_id, [])
        history.extend(messages)
        if self._max_messages is not None and len(history) > self._max_messages:
            del history[: len(history) - self._max_messages]
