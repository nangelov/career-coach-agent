"""Read-only Postgres query for the retention-purge sweep (S14, §6.18 / §7.6).

The *finder* side of the periodic retention job: it answers a single question — *which SSO
users have been inactive long enough to purge?* — and nothing else. Erasure itself is **not**
re-implemented here: the purge task feeds each returned id back through the existing
:meth:`~app.repositories.account.PostgresAccountRepository.delete_user` cascade (the SEC-05
Art. 17 primitive), so there is exactly one cascading-delete path in the codebase.

**"Last activity" definition (the crux of S14).** Derived from real usage, no denormalized
``last_activity_at`` column to keep in sync on every persisted turn (§tasks P9 note):

    last_activity(user) = COALESCE(MAX(messages.created_at over the user's conversations),
                                   users.created_at)

i.e. the most recent message the user's conversations hold, falling back to the account's
own ``created_at`` for a user who signed up but never sent a message. A user is *stale* when
that value is strictly older than the caller-supplied cutoff. This is a plain grouped
aggregate over existing columns — entirely practical at this scale — so no schema change.

``sessions.expires_at`` is deliberately **not** folded in: the Postgres ``sessions`` table is
written lazily (the authoritative live-session registry is Redis), so it under-reports login
activity, and ``expires_at`` is a *future* timestamp (when a session lapses), not a moment of
activity — using it as an activity proxy would be both unreliable and semantically wrong.

Lives in the repository layer alongside the ORM models it reads; all DB access goes through the
shared :class:`~app.repositories.postgres.PostgresConnectionProvider` (§4) — no ad-hoc engines.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from sqlalchemy import func, select

from app.repositories.models.identity import Conversation, Message, User
from app.repositories.postgres import PostgresConnectionProvider


class RetentionRepository(ABC):
    """Read-only port: enumerate users whose last activity predates a cutoff (§6.18).

    One narrow query; the purge task depends on this interface (or its structural shape) and
    on the separate :meth:`delete_user` eraser — never on a driver.
    """

    @abstractmethod
    async def stale_user_ids(self, *, older_than: datetime) -> list[str]:
        """Return the ids of users whose last activity is strictly older than ``older_than``.

        Never raises for an empty database (returns ``[]``); read-only — mutates nothing.
        """


class PostgresRetentionRepository(RetentionRepository):
    """Postgres-backed :class:`RetentionRepository` — one grouped aggregate, no writes (§6.18)."""

    def __init__(self, provider: PostgresConnectionProvider) -> None:
        self._provider = provider

    @classmethod
    def from_provider(cls, provider: PostgresConnectionProvider) -> PostgresRetentionRepository:
        """Build over the shared Postgres connection provider (§4)."""
        return cls(provider)

    async def stale_user_ids(self, *, older_than: datetime) -> list[str]:
        # last_activity = COALESCE(MAX(messages.created_at), users.created_at). LEFT JOINs so a
        # user with no conversations/messages still appears (MAX → NULL → falls back to the
        # account's created_at). HAVING keeps only users whose last activity is strictly older
        # than the cutoff. String ids so the caller feeds them straight into delete_user.
        last_activity = func.coalesce(func.max(Message.created_at), User.created_at)
        stmt = (
            select(User.id)
            .select_from(User)
            .outerjoin(Conversation, Conversation.user_id == User.id)
            .outerjoin(Message, Message.conversation_id == Conversation.id)
            .group_by(User.id, User.created_at)
            .having(last_activity < older_than)
        )
        async with self._provider.session() as db:
            rows = (await db.execute(stmt)).scalars().all()
        return [str(row) for row in rows]
