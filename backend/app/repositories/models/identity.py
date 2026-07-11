"""Identity, conversation & document ORM models (design §4 — Postgres relational + JSONB).

The first real table group of the v2 schema (P2-03). Every class subclasses the shared
:class:`~app.repositories.postgres.Base` so they land on the one ``metadata`` Alembic
targets and the repository layer queries through.

Design constraints baked into the schema here:

* **SSO-only, no passwords (§7.1).** :class:`User` has ``provider`` + ``sub`` (one row per
  OIDC identity, enforced by a unique constraint) and *no* password/credential column.
* **JSONB, not JSON (§4).** ``settings`` / profile / preference documents use
  :class:`~sqlalchemy.dialects.postgresql.JSONB` for Postgres-native indexing later.
* **Stable ``message_id`` (§5.5).** :attr:`Message.message_id` is the ``uuid4().hex``
  string minted by :class:`~app.services.chat.ChatService`; it is unique-indexed and is
  the natural key :class:`MessageFeedback` references (so the P9 feedback endpoint keys on
  the same id the stream already emitted).
* **Client-supplied session id.** :attr:`Session.id` is a *string* PK, not a DB-generated
  UUID, because the id is minted client-side (``crypto.randomUUID()``, P1-08) and arrives
  as ``session_id: str`` on ``ChatRequest`` — the schema must store whatever shape the app
  already generates without forcing a type change.
* **GDPR-delete posture (§4).** Deleting a user cascades to their profile, preferences,
  sessions, conversations, messages and per-message feedback. Free-text product
  :class:`Feedback` is the deliberate exception — its user/session FKs are ``ON DELETE SET
  NULL`` so product feedback (and its analytics value) outlives the account it came from.

Guests are Redis-only for message history (§4: *"Guests get NO persisted history"*): the
nullable ``user_id`` FKs let a :class:`Session` exist without a user as the identity anchor,
but persisting guest conversation content into these tables is an app-layer concern that
this schema intentionally does not force.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.repositories.models._mixins import CreatedAtMixin
from app.repositories.postgres import Base

#: Allowed chat roles — kept in lockstep with ``app.llm.types.Role`` so a persisted
#: message can always be re-hydrated into a :class:`~app.llm.types.ChatMessage`.
_ROLE_VALUES = ("system", "user", "assistant", "tool")
#: Allowed per-message reactions (§5.5 — thumb up / down).
_RATING_VALUES = ("up", "down")


class User(CreatedAtMixin, Base):
    """A logged-in identity — one row per OIDC ``(provider, sub)`` pair (§7.1).

    No password/credential column exists by design: authentication happens entirely at
    Google/LinkedIn and the app only ever stores the returned ``sub``, email and name.
    """

    __tablename__ = "users"
    __table_args__ = (
        # One identity per provider: (google, <sub>) is unique. Also the natural lookup
        # key when resolving an OIDC callback to an existing user.
        UniqueConstraint("provider", "sub", name="uq_users_provider_sub"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    sub: Mapped[str] = mapped_column(String(255), nullable=False)
    # Requested via the minimal ``openid email profile`` scope (§7.1). Indexed for
    # admin/support lookups; not unique (a person may sign in via two providers).
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Administrator flag (§7 AuthZ) — gates admin-only endpoints (e.g. the feedback-read
    # endpoint that replaces v1's ``GET /get-feedback?key=<HF_TOKEN>``). Defaults to false;
    # granted out-of-band by a trusted operator (see docs/admin-access.md), never by any
    # self-service route, so no request can escalate its own privilege.
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    # Free-form user settings document (§4: ``settings JSONB``).
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    profile: Mapped[Profile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    preference: Mapped[Preference | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Profile(CreatedAtMixin, Base):
    """The structured CV/profile document for a user (§4) — one per user, reused across chats.

    Skills / experience / education / goals live inside the ``data`` JSONB blob rather than
    as columns; the shape is owned by the ingestion/profile layer, not the schema.
    """

    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # unique → at most one profile per user (§4: "one structured CV/profile per user").
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="profile")


class Preference(CreatedAtMixin, Base):
    """Explicit, user-editable personalization settings (§5.4) — one per user.

    Tone / formality / language / do-and-don't live in ``data`` JSONB; this store is the
    *authoritative* personalization signal (distinct from the inferred ``user_memories``
    that P2-04 adds).
    """

    __tablename__ = "preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="preference")


class Session(CreatedAtMixin, Base):
    """A chat session — the identity-linkage anchor (§4).

    ``id`` is a **string** PK because it is minted client-side (``crypto.randomUUID()``)
    and travels as ``session_id: str`` on ``ChatRequest``. ``user_id`` is nullable:
    **null means guest** (guests get no persisted message history — that lives in Redis
    only — but the session row still exists as the identity anchor for a logged-in user).
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User | None] = relationship(back_populates="sessions")
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Conversation(CreatedAtMixin, Base):
    """Groups ordered messages under a session (and, when logged in, a user) — §4."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable: a guest conversation has no user (though guests aren't persisted here in
    # practice — §4). Cascades so a GDPR user-delete removes their conversations.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped[Session] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(CreatedAtMixin, Base):
    """One ordered message in a conversation (§4).

    :attr:`message_id` is the app-level natural key (``uuid4().hex`` from ``ChatService``);
    it is unique-indexed and is what :class:`MessageFeedback` / the P9 feedback endpoint
    reference — distinct from the surrogate ``id`` PK so the app never has to learn the DB
    surrogate. ``role`` is constrained to the same values as ``app.llm.types.Role``.
    """

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            f"role IN ({', '.join(repr(v) for v in _ROLE_VALUES)})",
            name="ck_messages_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # ``uuid4().hex`` → 32 hex chars, no dashes (matches ChatService). Unique natural key.
    message_id: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, default=lambda: uuid4().hex
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # Nullable: an assistant turn that only emitted tool calls has no text content.
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Agent-trace metadata (tool calls, timings) — future-proofing for P4's multi-agent
    # trace; not populated yet (§4 "agent-trace metadata (JSONB)").
    trace: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    feedback: Mapped[list[MessageFeedback]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class MessageFeedback(CreatedAtMixin, Base):
    """Per-message 👍/👎 reaction (§5.5) — the schema the P9 feedback endpoint writes to.

    References :attr:`Message.message_id` (the stable app id), not the surrogate PK, so the
    endpoint keys on the same id the chat stream emitted. Cascades on user/message delete —
    it is signal tied to the learning loop and the message itself, so it does not outlive them.
    """

    __tablename__ = "message_feedback"
    __table_args__ = (
        CheckConstraint(
            f"rating IN ({', '.join(repr(v) for v in _RATING_VALUES)})",
            name="ck_message_feedback_rating",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("messages.message_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    message: Mapped[Message] = relationship(back_populates="feedback")


class Feedback(CreatedAtMixin, Base):
    """Free-text product feedback (§4) — replaces v1's per-day JSON files.

    User/session FKs are ``ON DELETE SET NULL`` (not cascade): product feedback and its
    analytics value are intended to **outlive** the account that submitted it, so a GDPR
    user-delete detaches the row rather than erasing it. ``contact`` mirrors v1's optional
    contact field.
    """

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact: Mapped[str | None] = mapped_column(String(320), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
