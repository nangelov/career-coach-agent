"""Postgres adapter for the :class:`~app.services.conversation_store.ConversationStore` port.

Durably persists a logged-in user's chat turns to the P2-03 identity schema
(``sessions`` → ``conversations`` → ``messages``) so account history survives a restart
or a Redis eviction (design §4: *"Guests get NO persisted history"* — logged-in users do).

Lives in its own module (rather than swelling ``repositories/postgres.py``, which is the
engine/pool foundation) alongside the P2-03 ORM models it maps to. All DB access goes
through the shared :class:`~app.repositories.postgres.PostgresConnectionProvider` from
P2-01 — no ad-hoc engines/connections.

Interim identity note (P3 gap): ``user_id`` is the string form of the authenticated
``users.id`` UUID. :meth:`persist_turn` **assumes that user row already exists** (P3 creates
it at login) — the ``sessions``/``conversations`` FKs to ``users.id`` require it. If it does
not exist the FK insert raises, which the chat service catches best-effort (persistence
never breaks the user-visible stream). It *does* get-or-create the ``sessions`` and
``conversations`` rows, since those may not exist yet on a session's first persisted turn.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.llm.types import ChatMessage, Role
from app.repositories.models.identity import Conversation, Message, Session
from app.repositories.postgres import PostgresConnectionProvider
from app.services.conversation_store import ConversationStore

#: Default rehydration cap when none is injected — mirrors the ``SESSION_MEMORY_MAX_MESSAGES``
#: default (and ``RedisSessionMemory.max_messages``) so a directly-constructed store bounds
#: history identically to the Redis working memory.
DEFAULT_HISTORY_LIMIT = 100


class PostgresConversationStore(ConversationStore):
    """Postgres-backed durable conversation store (design §4).

    Writes user + assistant turns to the ``conversations`` / ``messages`` tables and reads
    them back to rehydrate context after a restart. Only the user message and the final
    (or partial-on-cancel) assistant answer are persisted per turn — the internal tool
    round-trip scaffolding is deliberately not stored, keeping the durable history a clean
    user↔assistant transcript (the Redis working memory still carries the tool messages
    within a live session).
    """

    def __init__(
        self,
        provider: PostgresConnectionProvider,
        *,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> None:
        self._provider = provider
        # Injected at construction (not read from the global ``settings`` at query time),
        # matching every sibling adapter's ``from_settings`` pattern (RedisSessionMemory,
        # RedisCancelRegistry, …) — keeps the cap explicit and the adapter test-configurable.
        self._history_limit = max(1, history_limit)

    @classmethod
    def from_settings(
        cls,
        provider: PostgresConnectionProvider,
        config: Settings = settings,
    ) -> PostgresConversationStore:
        """Build from application config (rehydration cap sourced from ``app/config.py``).

        Bounds the rehydrated context to ``SESSION_MEMORY_MAX_MESSAGES`` — the same cap as
        the Redis working memory — so a long account conversation does not load its entire
        transcript into the model context after a restart.
        """
        return cls(provider, history_limit=config.SESSION_MEMORY_MAX_MESSAGES)

    async def persist_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        conversation_id: str | None,
        user_message: ChatMessage,
        assistant_message: ChatMessage | None,
    ) -> str:
        uid = uuid.UUID(user_id)
        async with self._provider.session() as db:
            # Get-or-create the session row (the identity anchor). The id is client-minted
            # and may not have been persisted yet; ON CONFLICT DO NOTHING makes this
            # idempotent across a session's turns without a prior SELECT.
            await db.execute(
                pg_insert(Session)
                .values(id=session_id, user_id=uid)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            conv_id = await self._resolve_conversation(db, conversation_id, session_id, uid)

            # One wall-clock timestamp per turn: turns are ordered by ``created_at``, and
            # the user↔assistant pair within a single turn (which share this timestamp) is
            # disambiguated by the role tiebreaker in :meth:`load_history`.
            now = datetime.now(UTC)
            # The user message gets an auto ``message_id`` (ORM default); the assistant
            # message keeps the turn's stable ``message_id`` (§5.5) so a later 👍/👎 resolves.
            db.add(
                Message(
                    conversation_id=conv_id,
                    role=user_message.role,
                    content=user_message.content,
                    created_at=now,
                )
            )
            if assistant_message is not None:
                db.add(
                    Message(
                        conversation_id=conv_id,
                        message_id=assistant_message.message_id or uuid.uuid4().hex,
                        role=assistant_message.role,
                        content=assistant_message.content,
                        created_at=now,
                    )
                )
            await db.commit()
            return str(conv_id)

    async def _resolve_conversation(
        self,
        db: AsyncSession,
        conversation_id: str | None,
        session_id: str,
        uid: uuid.UUID,
    ) -> uuid.UUID:
        """Return the conversation id for this turn, creating one on a session's first turn.

        Concurrency assumption: this SELECT-then-INSERT get-or-create is **not** guarded by a
        DB-level uniqueness constraint on ``conversations.session_id``, so two *concurrent*
        first-turns for the same session could each miss the SELECT and create a second
        conversation, splitting the history. That is safe here because the chat pipeline
        allows **one in-flight stream per session** (the SSE turn + the Redis cancel flag are
        per-session, and a client fires the next turn only after the current stream ends), so
        first-turns for a session are serialized in practice. If a future phase allows
        concurrent turns per session (e.g. multi-tab), add a unique constraint on
        ``conversations.session_id`` (or an ``ON CONFLICT`` upsert) to enforce this invariant.
        """
        if conversation_id is not None:
            return uuid.UUID(conversation_id)
        # One conversation per session at this phase: reuse the session's existing one
        # (oldest) if present, else create it.
        existing = (
            await db.execute(
                select(Conversation.id)
                .where(Conversation.session_id == session_id)
                .order_by(Conversation.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        conversation = Conversation(session_id=session_id, user_id=uid)
        db.add(conversation)
        await db.flush()
        return conversation.id

    async def load_history(self, *, user_id: str, session_id: str) -> list[ChatMessage]:
        uid = uuid.UUID(user_id)
        async with self._provider.session() as db:
            # Order by turn time, then by role so the user↔assistant pair persisted with a
            # shared per-turn timestamp is disambiguated user-first (see :meth:`persist_turn`).
            role_rank = case(
                (Message.role == "user", 0),
                (Message.role == "assistant", 1),
                else_=2,
            )
            # Bound the rehydrated context to the same cap as the Redis working memory
            # (``history_limit``, injected from ``SESSION_MEMORY_MAX_MESSAGES``) so a long
            # account conversation does not load its entire transcript into the model context
            # (and blow the context window) after a restart. Fetch the most-recent N (DESC),
            # then reverse back to chronological order so the caller/model sees oldest→newest.
            stmt = (
                select(Message)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .where(Conversation.session_id == session_id, Conversation.user_id == uid)
                .order_by(Message.created_at.desc(), role_rank.desc())
                .limit(self._history_limit)
            )
            rows = list((await db.execute(stmt)).scalars().all())
            rows.reverse()
            return [
                ChatMessage(
                    role=cast(Role, message.role),
                    content=message.content,
                    message_id=message.message_id,
                )
                for message in rows
            ]
