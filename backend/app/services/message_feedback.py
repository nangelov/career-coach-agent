"""Per-message feedback capture seam (Postgres adapter in ``repositories.message_feedback_store``).

``POST /api/messages/{message_id}/feedback`` (P9-01) needs three capabilities against the
``message_feedback`` table (§5.5): record (upsert) the caller's 👍/👎 + reason for one of
*their own* messages, and — for the later LangMem learn step (P9-03) — read a message's
feedback and list a user's recent thumbs-down. That trio gets a narrow port here, following
the interface-before-implementation idiom used across the codebase (``ProfileStore``,
``FeedbackReader``, …): this module defines the port plus a process-local implementation for
tests; the **Postgres-backed** adapter
(:class:`~app.repositories.message_feedback_store.PostgresMessageFeedbackStore`) lives in the
repository layer.

**Ownership is part of the contract, not the router.** :meth:`MessageFeedbackStore.record`
takes the caller's identity (``user_id`` for a logged-in user, else the guest ``session_id``)
and returns ``None`` when the message does not exist *or* is not the caller's — the router
maps that single ``None`` to a uniform ``404`` (never distinguishing "missing" from
"not yours", so it cannot be used to probe another user's message ids; §7 AuthZ). A message
has exactly one owner (one conversation → one session → one user), so a caller may rate a
message at most once; a resubmission replaces that same row (idempotent).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime

from app.schemas.message_feedback import MessageFeedbackResponse, MessageRating


class MessageFeedbackStore(ABC):
    """Capture / read per-message 👍/👎 feedback (§5.5 ``message_feedback``).

    Implementations own storage (process-local here, Postgres in the repository layer); the
    feedback endpoint depends only on this interface. Every method is scoped to the caller —
    the store never exposes a way to write another user's row (ownership is validated in
    :meth:`record`) and reads are keyed on ids the caller already owns.
    """

    @abstractmethod
    async def record(
        self,
        *,
        message_id: str,
        rating: MessageRating,
        reason: str | None,
        user_id: str | None,
        session_id: str,
    ) -> MessageFeedbackResponse | None:
        """Upsert the caller's feedback for ``message_id``, or ``None`` if not theirs/absent.

        Validates the message exists and belongs to the caller — a logged-in user owns a
        message whose conversation is theirs (``user_id``); a guest owns one whose conversation
        is on their ``session_id``. On success the feedback is inserted, or the caller's
        existing row for that message is replaced (idempotent — resubmitting flips the rating /
        edits the reason in place, never duplicates). Returns the stored feedback, or ``None``
        when the message is unknown or not the caller's (the router turns that into a ``404``).
        """

    @abstractmethod
    async def get_for_message(self, message_id: str) -> MessageFeedbackResponse | None:
        """Return the stored feedback for ``message_id``, or ``None`` if none exists.

        Read seam for the P9-03 learn step (and tests): a message carries at most one feedback
        row, so this is a single-row lookup.
        """

    @abstractmethod
    async def list_recent_downvotes(
        self, user_id: str, *, limit: int
    ) -> list[MessageFeedbackResponse]:
        """List a user's most-recent thumbs-**down** feedback, newest first (≤ ``limit``).

        The signal the P9-03 LangMem learn step consumes to demote memories / adjust behavior:
        the reasons a user marked answers unhelpful. Empty when the user has no down-votes.
        """


@dataclass
class _StoredFeedback:
    """One process-local feedback row (test double), keyed by ``message_id``."""

    response: MessageFeedbackResponse
    user_id: str | None
    session_id: str


@dataclass
class MessageOwner:
    """The owner of a message, seeded into :class:`InMemoryMessageFeedbackStore` for tests.

    Mirrors what the Postgres adapter derives by joining ``messages`` → ``conversations``: a
    message belongs to a logged-in user (``user_id``) or, for a guest, to a ``session_id``.
    """

    user_id: str | None = None
    session_id: str | None = None


class InMemoryMessageFeedbackStore(MessageFeedbackStore):
    """Process-local :class:`MessageFeedbackStore` — test double only.

    Seeded with the ownership of known messages (``owners``) so :meth:`record` can enforce the
    same own-data-only rule the Postgres adapter does — a caller rating a message they do not
    own gets ``None`` (→ ``404``), exactly like an unknown message. Feedback is keyed by
    ``message_id`` (one owner per message), so a resubmission replaces the same entry. Not for
    production.
    """

    def __init__(self, owners: dict[str, MessageOwner] | None = None) -> None:
        self._owners = dict(owners or {})
        self._by_message: dict[str, _StoredFeedback] = {}

    def _owns(self, owner: MessageOwner, user_id: str | None, session_id: str) -> bool:
        if user_id is not None:
            return owner.user_id == user_id
        return owner.session_id == session_id

    async def record(
        self,
        *,
        message_id: str,
        rating: MessageRating,
        reason: str | None,
        user_id: str | None,
        session_id: str,
    ) -> MessageFeedbackResponse | None:
        owner = self._owners.get(message_id)
        if owner is None or not self._owns(owner, user_id, session_id):
            return None
        response = MessageFeedbackResponse(
            message_id=message_id,
            rating=rating,
            reason=reason,
            created_at=datetime.now(UTC),
        )
        self._by_message[message_id] = _StoredFeedback(
            response=response, user_id=user_id, session_id=session_id
        )
        return response

    async def get_for_message(self, message_id: str) -> MessageFeedbackResponse | None:
        stored = self._by_message.get(message_id)
        return stored.response if stored is not None else None

    async def list_recent_downvotes(
        self, user_id: str, *, limit: int
    ) -> list[MessageFeedbackResponse]:
        rows = [
            stored
            for stored in self._by_message.values()
            if stored.user_id == user_id and stored.response.rating == "down"
        ]
        rows.sort(key=lambda s: s.response.created_at, reverse=True)
        return [s.response for s in rows[: max(0, limit)]]
