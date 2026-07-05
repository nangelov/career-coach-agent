"""Durable conversation persistence seam (Postgres-backed for logged-in users).

Design §4 ("Guests get NO persisted history"): a **logged-in** user's chat history must
survive a restart / Redis eviction, so it is written to Postgres in addition to the
Redis working memory (:mod:`app.services.session_memory`). Guests stay Redis-only.

This module defines the narrow **port** the chat service depends on
(:class:`ConversationStore`); the concrete Postgres adapter
(:class:`~app.repositories.conversation_store.PostgresConversationStore`) lives in the
repository layer and satisfies this same interface — services keep depending only on the
port (interface-before-implementation), and the datastore access lives in ``repositories/``,
mirroring the :class:`~app.services.session_memory.SessionMemory` /
:class:`~app.services.cancellation.CancelRegistry` ports-and-adapters shape.

.. note::
   There is no in-memory production implementation here (unlike ``SessionMemory``): the
   chat service treats an **absent** store (``None``) as "persistence off" — the guest
   path and any deployment without a Postgres provider simply skip durable writes. Tests
   inject a fake implementing this ABC.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.llm.types import ChatMessage


class ConversationStore(ABC):
    """Persist / rehydrate a logged-in user's conversation to durable storage.

    The **interim identity contract** (see :class:`~app.schemas.chat.ChatRequest`): real
    SSO/JWT auth is P3, so ``user_id`` here is a caller-supplied stand-in for the
    JWT-derived identity P3 will provide — concretely, the string form of the
    authenticated user's ``users.id`` (created at login in P3). A ``None`` ``user_id`` at
    the call site means *guest* and the service never reaches this port at all.
    """

    @abstractmethod
    async def persist_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        conversation_id: str | None,
        user_message: ChatMessage,
        assistant_message: ChatMessage | None,
    ) -> str:
        """Durably store one completed turn; return the conversation id it landed in.

        Args:
            user_id: The logged-in user's id (see the class docstring's interim contract).
            session_id: The client-minted chat session id (``ChatRequest.session_id``).
            conversation_id: The conversation to append to, or ``None`` to
                get-or-create the session's conversation (first turn of a session).
            user_message: The user's message for this turn.
            assistant_message: The assistant's answer (carrying its stable
                ``message_id``), or ``None`` when a turn was cancelled before any content
                was produced — the user's question is still preserved.

        Returns:
            The conversation id the turn was written to (stable across a session's turns,
            so a caller may thread it back in on the next turn instead of ``None``).
        """

    @abstractmethod
    async def load_history(self, *, user_id: str, session_id: str) -> list[ChatMessage]:
        """Return the durably-stored messages for ``user_id`` + ``session_id``, in order.

        Used to rehydrate a turn's context after a restart / Redis eviction, when the
        Redis :class:`~app.services.session_memory.SessionMemory` has lost the session but
        Postgres still holds it. Returns an empty list when nothing is stored.
        """
