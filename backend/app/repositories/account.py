"""Postgres adapter for the :class:`~app.services.account.AccountRepository` port (SEC-05).

Backs ``DELETE /api/me`` (Art. 17 erasure) and ``GET /api/me/export`` (Art. 20 portability,
§7.6). Lives in the repository layer alongside the ORM models it reads; all DB access goes
through the shared :class:`~app.repositories.postgres.PostgresConnectionProvider` (§4) — no
ad-hoc engines. Services depend only on the port, never on this adapter or SQLAlchemy.

Two design points:

* **Erasure is a single cascading delete, plus a feedback PII scrub.** Every user-owned
  table's ``user_id`` FK is ``ondelete="CASCADE"`` (P2 migrations), so
  ``DELETE FROM users WHERE id = :uid`` removes the entire Postgres footprint — no hand-written
  per-table deletes. The one exception is ``feedback``, whose ``user_id`` is ``ON DELETE SET
  NULL`` (product feedback deliberately outlives the account, §4). Its optional ``contact``
  column is a user-typed email — directly-identifying PII that a plain SET NULL would leave
  behind, undercutting the anonymization Art. 17 requires. So erasure first nulls
  ``feedback.contact`` for the user (in the same transaction as the cascade), leaving a truly
  anonymous, detached feedback row (content retained, contact + user_id gone). Idempotent (an
  unknown id scrubs/deletes zero rows) and a malformed id is a no-op.
* **Export excludes raw embeddings and is strictly caller-scoped.** Each section selects
  explicit columns (never ``kb_chunks.embedding`` / ``user_memories.embedding``) and filters to
  ``user_id = caller`` — directly, or through an owned parent (messages via their conversation,
  chunks via their document, milestones/tasks via their goal). Shared/curated KB rows
  (``user_id IS NULL``) are never selected. UUID/date/datetime values are coerced to JSON-safe
  strings here so the router can hand the model straight back as a downloadable document.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Row, Select, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models.dashboard import (
    DashboardTask,
    Goal,
    Milestone,
    Pdp,
    ProgressEntry,
)
from app.repositories.models.identity import (
    Conversation,
    Feedback,
    Message,
    MessageFeedback,
    Preference,
    Profile,
    User,
)
from app.repositories.models.knowledge import KbChunk, KbDocument, UserMemory
from app.repositories.postgres import PostgresConnectionProvider
from app.schemas.account import AccountExport, ExportRow
from app.services.account import AccountRepository


def _jsonable(value: Any) -> Any:
    """Coerce a scalar column value to a JSON-safe form (UUID/date/datetime → str).

    JSONB columns are already ``dict``/``list`` of JSON-safe scalars, so they pass through
    unchanged; only the id and timestamp types need coercion for a stable downloaded document.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _row_to_dict(row: Row[Any]) -> ExportRow:
    """Turn a selected ``Row`` into a JSON-safe ``{column: value}`` mapping."""
    return {key: _jsonable(val) for key, val in row._mapping.items()}


class PostgresAccountRepository(AccountRepository):
    """Postgres-backed :class:`AccountRepository` — cascade erasure + scoped export (§7.6)."""

    def __init__(self, provider: PostgresConnectionProvider) -> None:
        self._provider = provider

    @classmethod
    def from_provider(cls, provider: PostgresConnectionProvider) -> PostgresAccountRepository:
        """Build over the shared Postgres connection provider (§4)."""
        return cls(provider)

    @staticmethod
    def _as_uuid(user_id: str) -> uuid.UUID | None:
        """Parse ``user_id`` to a UUID, or ``None`` if malformed (fail-safe)."""
        try:
            return uuid.UUID(user_id)
        except ValueError:
            return None

    async def delete_user(self, user_id: str) -> None:
        uid = self._as_uuid(user_id)
        if uid is None:
            return
        # Single cascading delete: the ``ondelete="CASCADE"`` FKs on every user-owned table
        # remove the whole footprint. ``feedback`` is the one SET NULL exception (it outlives
        # the account, §4) — scrub its ``contact`` PII first, in the same transaction, so the
        # detached row is truly anonymous. Both touch zero rows for an unknown id (idempotent).
        async with self._provider.session() as db:
            await db.execute(update(Feedback).where(Feedback.user_id == uid).values(contact=None))
            await db.execute(delete(User).where(User.id == uid))
            await db.commit()

    async def export(self, user_id: str) -> AccountExport:
        uid = self._as_uuid(user_id)
        if uid is None:
            return AccountExport()
        async with self._provider.session() as db:
            return AccountExport(
                user=await self._one(db, self._user_stmt(uid)),
                profile=await self._one(db, self._profile_stmt(uid)),
                preferences=await self._one(db, self._preferences_stmt(uid)),
                conversations=await self._many(db, self._conversations_stmt(uid)),
                messages=await self._many(db, self._messages_stmt(uid)),
                message_feedback=await self._many(db, self._message_feedback_stmt(uid)),
                feedback=await self._many(db, self._feedback_stmt(uid)),
                kb_documents=await self._many(db, self._kb_documents_stmt(uid)),
                kb_chunks=await self._many(db, self._kb_chunks_stmt(uid)),
                user_memories=await self._many(db, self._user_memories_stmt(uid)),
                pdps=await self._many(db, self._pdps_stmt(uid)),
                goals=await self._many(db, self._goals_stmt(uid)),
                milestones=await self._many(db, self._milestones_stmt(uid)),
                tasks=await self._many(db, self._tasks_stmt(uid)),
                progress_entries=await self._many(db, self._progress_entries_stmt(uid)),
            )

    @staticmethod
    async def _one(db: AsyncSession, stmt: Select[Any]) -> ExportRow | None:
        row = (await db.execute(stmt)).first()
        return _row_to_dict(row) if row is not None else None

    @staticmethod
    async def _many(db: AsyncSession, stmt: Select[Any]) -> list[ExportRow]:
        rows = (await db.execute(stmt)).all()
        return [_row_to_dict(row) for row in rows]

    # --- per-table SELECTs (explicit columns; embeddings never selected) ------------------ #

    @staticmethod
    def _user_stmt(uid: uuid.UUID) -> Select[Any]:
        return select(
            User.id,
            User.provider,
            User.sub,
            User.email,
            User.display_name,
            User.settings,
            User.created_at,
        ).where(User.id == uid)

    @staticmethod
    def _profile_stmt(uid: uuid.UUID) -> Select[Any]:
        return select(Profile.id, Profile.data, Profile.created_at, Profile.updated_at).where(
            Profile.user_id == uid
        )

    @staticmethod
    def _preferences_stmt(uid: uuid.UUID) -> Select[Any]:
        return select(
            Preference.id, Preference.data, Preference.created_at, Preference.updated_at
        ).where(Preference.user_id == uid)

    @staticmethod
    def _conversations_stmt(uid: uuid.UUID) -> Select[Any]:
        return (
            select(
                Conversation.id,
                Conversation.session_id,
                Conversation.title,
                Conversation.summary,
                Conversation.created_at,
            )
            .where(Conversation.user_id == uid)
            .order_by(Conversation.created_at, Conversation.id)
        )

    @staticmethod
    def _messages_stmt(uid: uuid.UUID) -> Select[Any]:
        return (
            select(
                Message.message_id,
                Message.conversation_id,
                Message.role,
                Message.content,
                Message.trace,
                Message.created_at,
            )
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(Conversation.user_id == uid)
            .order_by(Message.created_at, Message.id)
        )

    @staticmethod
    def _message_feedback_stmt(uid: uuid.UUID) -> Select[Any]:
        return (
            select(
                MessageFeedback.id,
                MessageFeedback.message_id,
                MessageFeedback.rating,
                MessageFeedback.reason,
                MessageFeedback.created_at,
            )
            .where(MessageFeedback.user_id == uid)
            .order_by(MessageFeedback.created_at, MessageFeedback.id)
        )

    @staticmethod
    def _feedback_stmt(uid: uuid.UUID) -> Select[Any]:
        return (
            select(
                Feedback.id,
                Feedback.contact,
                Feedback.content,
                Feedback.created_at,
            )
            .where(Feedback.user_id == uid)
            .order_by(Feedback.created_at, Feedback.id)
        )

    @staticmethod
    def _kb_documents_stmt(uid: uuid.UUID) -> Select[Any]:
        return (
            select(
                KbDocument.id,
                KbDocument.title,
                KbDocument.source,
                KbDocument.source_type,
                KbDocument.content,
                KbDocument.meta,
                KbDocument.created_at,
                KbDocument.updated_at,
            )
            .where(KbDocument.user_id == uid)
            .order_by(KbDocument.created_at, KbDocument.id)
        )

    @staticmethod
    def _kb_chunks_stmt(uid: uuid.UUID) -> Select[Any]:
        # Joined through the owning document; embedding column deliberately not selected.
        return (
            select(
                KbChunk.id,
                KbChunk.kb_document_id,
                KbChunk.chunk_index,
                KbChunk.content,
                KbChunk.meta,
                KbChunk.created_at,
            )
            .join(KbDocument, KbChunk.kb_document_id == KbDocument.id)
            .where(KbDocument.user_id == uid)
            .order_by(KbChunk.kb_document_id, KbChunk.chunk_index)
        )

    @staticmethod
    def _user_memories_stmt(uid: uuid.UUID) -> Select[Any]:
        # embedding column deliberately not selected (derived artifact, §7.6).
        return (
            select(
                UserMemory.id,
                UserMemory.text,
                UserMemory.memory_type,
                UserMemory.confidence,
                UserMemory.source_message_id,
                UserMemory.created_at,
                UserMemory.updated_at,
            )
            .where(UserMemory.user_id == uid)
            .order_by(UserMemory.created_at, UserMemory.id)
        )

    @staticmethod
    def _pdps_stmt(uid: uuid.UUID) -> Select[Any]:
        return (
            select(
                Pdp.id,
                Pdp.career_goal,
                Pdp.target_date,
                Pdp.content,
                Pdp.created_at,
            )
            .where(Pdp.user_id == uid)
            .order_by(Pdp.created_at, Pdp.id)
        )

    @staticmethod
    def _goals_stmt(uid: uuid.UUID) -> Select[Any]:
        return (
            select(
                Goal.id,
                Goal.title,
                Goal.target_role,
                Goal.target_date,
                Goal.status,
                Goal.source,
                Goal.created_at,
                Goal.updated_at,
            )
            .where(Goal.user_id == uid)
            .order_by(Goal.created_at, Goal.id)
        )

    @staticmethod
    def _milestones_stmt(uid: uuid.UUID) -> Select[Any]:
        return (
            select(
                Milestone.id,
                Milestone.goal_id,
                Milestone.title,
                Milestone.due_date,
                Milestone.status,
                Milestone.source,
                Milestone.created_at,
                Milestone.updated_at,
            )
            .join(Goal, Milestone.goal_id == Goal.id)
            .where(Goal.user_id == uid)
            .order_by(Milestone.created_at, Milestone.id)
        )

    @staticmethod
    def _tasks_stmt(uid: uuid.UUID) -> Select[Any]:
        return (
            select(
                DashboardTask.id,
                DashboardTask.goal_id,
                DashboardTask.milestone_id,
                DashboardTask.title,
                DashboardTask.description,
                DashboardTask.due_date,
                DashboardTask.status,
                DashboardTask.source,
                DashboardTask.created_at,
                DashboardTask.updated_at,
            )
            .join(Goal, DashboardTask.goal_id == Goal.id)
            .where(Goal.user_id == uid)
            .order_by(DashboardTask.created_at, DashboardTask.id)
        )

    @staticmethod
    def _progress_entries_stmt(uid: uuid.UUID) -> Select[Any]:
        return (
            select(
                ProgressEntry.id,
                ProgressEntry.goal_id,
                ProgressEntry.task_id,
                ProgressEntry.note,
                ProgressEntry.source,
                ProgressEntry.created_at,
            )
            .where(ProgressEntry.user_id == uid)
            .order_by(ProgressEntry.created_at, ProgressEntry.id)
        )
