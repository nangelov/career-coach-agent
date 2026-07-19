"""Postgres adapter for the :class:`~app.services.message_feedback.MessageFeedbackStore` port.

Writes and reads the per-message 👍/👎 reactions (§5.5 ``message_feedback`` table) that
``POST /api/messages/{message_id}/feedback`` (P9-01) captures — the raw signal the P9-03
LangMem learn step later consumes.

Lives in the repository layer alongside the ORM model it maps; all DB access goes through the
shared :class:`~app.repositories.postgres.PostgresConnectionProvider` (§4) — no ad-hoc
engines/connections. Routers/services depend only on the ``MessageFeedbackStore`` port, never
on this adapter or SQLAlchemy directly (§8 layering).

Ownership is enforced here (not the router): :meth:`record` resolves the message's owner by
joining ``messages`` → ``conversations`` and compares it to the caller before writing. A
logged-in user owns a message whose conversation carries their ``user_id``; a guest owns one
whose conversation is on their ``session_id`` (guest history is Redis-only in practice, so a
guest rating an un-persisted message simply reads as "not found"). A message has exactly one
owner, so the ``message_feedback.message_id`` unique constraint (migration 0009) makes the
upsert a single row per message — a resubmission replaces it in one round-trip.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.repositories.models.identity import Conversation, Message, MessageFeedback
from app.repositories.postgres import PostgresConnectionProvider
from app.schemas.message_feedback import MessageFeedbackResponse, MessageRating
from app.services.message_feedback import MessageFeedbackStore


class PostgresMessageFeedbackStore(MessageFeedbackStore):
    """Postgres-backed :class:`MessageFeedbackStore` — capture/read on ``message_feedback`` (§4)."""

    def __init__(self, provider: PostgresConnectionProvider) -> None:
        self._provider = provider

    @classmethod
    def from_provider(cls, provider: PostgresConnectionProvider) -> PostgresMessageFeedbackStore:
        """Build over the shared Postgres connection provider (§4)."""
        return cls(provider)

    @staticmethod
    def _owns(
        conv_user_id: uuid.UUID | None,
        conv_session_id: str,
        user_id: str | None,
        session_id: str,
    ) -> bool:
        """Own-data-only rule: a logged-in user matches by ``user_id``, a guest by ``session_id``.

        Logged-in users are matched on ``user_id`` (not ``session_id``) so feedback on a message
        from an earlier session — which carries a different ``session_id`` but the same
        ``user_id`` — is still recognized as theirs.
        """
        if user_id is not None:
            return conv_user_id is not None and str(conv_user_id) == user_id
        return conv_session_id == session_id

    async def record(
        self,
        *,
        message_id: str,
        rating: MessageRating,
        reason: str | None,
        user_id: str | None,
        session_id: str,
    ) -> MessageFeedbackResponse | None:
        owner_stmt = (
            select(Conversation.user_id, Conversation.session_id)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Message.message_id == message_id)
        )
        async with self._provider.session() as db:
            owner = (await db.execute(owner_stmt)).one_or_none()
            if owner is None or not self._owns(owner[0], owner[1], user_id, session_id):
                return None
            # Persist the message's *own* conversation ids (its user_id / session_id), not the
            # caller's: they are the authoritative owner (equal to the caller after the check)
            # and are guaranteed to satisfy the ``users`` / ``sessions`` FKs — the caller's
            # current session may be a fresh/Redis-only one that was never persisted, so keying
            # the row on it would violate ``message_feedback_session_id_fkey``.
            conv_user_id, conv_session_id = owner[0], owner[1]

            # One owner per message → conflict on the unique ``message_id`` (migration 0009):
            # first rating inserts, a resubmission replaces rating/reason and restamps
            # ``created_at`` so "recent down-votes" (P9-03) reflects the latest submission.
            stmt = (
                pg_insert(MessageFeedback)
                .values(
                    message_id=message_id,
                    user_id=conv_user_id,
                    session_id=conv_session_id,
                    rating=rating,
                    reason=reason,
                )
                .on_conflict_do_update(
                    index_elements=[MessageFeedback.message_id],
                    set_={
                        "rating": rating,
                        "reason": reason,
                        "user_id": conv_user_id,
                        "session_id": conv_session_id,
                        "created_at": func.now(),
                    },
                )
                .returning(MessageFeedback.created_at)
            )
            created_at = (await db.execute(stmt)).scalar_one()
            await db.commit()

        return MessageFeedbackResponse(
            message_id=message_id, rating=rating, reason=reason, created_at=created_at
        )

    async def get_for_message(self, message_id: str) -> MessageFeedbackResponse | None:
        stmt = select(MessageFeedback).where(MessageFeedback.message_id == message_id)
        async with self._provider.session() as db:
            row = (await db.execute(stmt)).scalar_one_or_none()
        return self._to_response(row) if row is not None else None

    async def list_recent_downvotes(
        self, user_id: str, *, limit: int
    ) -> list[MessageFeedbackResponse]:
        uid = self._as_uuid(user_id)
        if uid is None:
            return []
        stmt = (
            select(MessageFeedback)
            .where(MessageFeedback.user_id == uid, MessageFeedback.rating == "down")
            .order_by(MessageFeedback.created_at.desc(), MessageFeedback.id.desc())
            .limit(max(1, limit))
        )
        async with self._provider.session() as db:
            rows = list((await db.execute(stmt)).scalars().all())
        return [self._to_response(row) for row in rows]

    @staticmethod
    def _as_uuid(value: str | None) -> uuid.UUID | None:
        """Parse a ``users.id`` string to UUID, or ``None`` for a guest / malformed id."""
        if value is None:
            return None
        try:
            return uuid.UUID(value)
        except ValueError:
            return None

    @staticmethod
    def _to_response(row: MessageFeedback) -> MessageFeedbackResponse:
        return MessageFeedbackResponse(
            message_id=row.message_id,
            rating=row.rating,
            reason=row.reason,
            created_at=row.created_at,
        )
