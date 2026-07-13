"""Postgres adapter for the :class:`~app.services.user_store.UserStore` port.

Upserts a logged-in OIDC identity into the P2-03 ``users`` table on the natural key
``(provider, sub)`` (the ``uq_users_provider_sub`` constraint) and returns the resolved
:class:`~app.services.user_store.UserAccount`. This is the one place the SSO callback
(P3-02) touches the user table.

Lives in the repository layer alongside the ORM models it maps to; all DB access goes
through the shared :class:`~app.repositories.postgres.PostgresConnectionProvider` (§4) — no
ad-hoc engines/connections. Services depend only on the ``UserStore`` port, never on this
adapter or SQLAlchemy directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.repositories.models.identity import User
from app.repositories.postgres import PostgresConnectionProvider
from app.services.user_store import UserAccount, UserStore


class PostgresUserStore(UserStore):
    """Postgres-backed :class:`UserStore` — upsert on ``(provider, sub)`` (§7.1)."""

    def __init__(self, provider: PostgresConnectionProvider) -> None:
        self._provider = provider

    @classmethod
    def from_provider(cls, provider: PostgresConnectionProvider) -> PostgresUserStore:
        """Build over the shared Postgres connection provider (§4)."""
        return cls(provider)

    async def upsert(
        self,
        *,
        provider: str,
        sub: str,
        email: str,
        display_name: str | None,
        consent_policy_version: str | None = None,
        consent_accepted_at: datetime | None = None,
    ) -> UserAccount:
        """Insert the identity or update its email/display name, returning the row.

        Uses ``INSERT ... ON CONFLICT (provider, sub) DO UPDATE`` so a first login creates
        the row and a return login refreshes the mutable PII in one round-trip — no
        SELECT-then-branch race. Only the SSO-provided fields are ever written; there is no
        password/credential column (§7.1). ``RETURNING`` gives back the (possibly
        pre-existing) ``users.id`` that becomes the session JWT ``sub``.

        The consent gate (§6.22): ``consent_policy_version`` + ``consent_accepted_at`` are
        written on **both** the insert and the conflict-update, so a returning user
        re-accepting a bumped policy overwrites the stored version + timestamp — that is the
        re-prompt-on-version-bump mechanism. Both default to ``None`` (the columns are
        nullable) for the rare caller that creates a row outside the login flow.
        """
        stmt = (
            pg_insert(User)
            .values(
                provider=provider,
                sub=sub,
                email=email,
                display_name=display_name,
                consent_policy_version=consent_policy_version,
                consent_accepted_at=consent_accepted_at,
            )
            .on_conflict_do_update(
                constraint="uq_users_provider_sub",
                set_={
                    "email": email,
                    "display_name": display_name,
                    "consent_policy_version": consent_policy_version,
                    "consent_accepted_at": consent_accepted_at,
                },
            )
            .returning(User.id)
        )
        async with self._provider.session() as db:
            user_id = (await db.execute(stmt)).scalar_one()
            await db.commit()
        return UserAccount(
            id=str(user_id),
            provider=provider,
            sub=sub,
            email=email,
            display_name=display_name,
            consent_policy_version=consent_policy_version,
            consent_accepted_at=consent_accepted_at,
        )

    async def is_admin(self, user_id: str) -> bool:
        """Return whether the ``users`` row for ``user_id`` has ``is_admin = true`` (§7).

        A single indexed-PK lookup. A malformed id or a missing/deleted row resolves to
        ``False`` (fail-closed) rather than raising, so authorization denies rather than
        errors on an unknown caller.
        """
        try:
            uid = uuid.UUID(user_id)
        except ValueError:
            return False
        stmt = select(User.is_admin).where(User.id == uid)
        async with self._provider.session() as db:
            result = (await db.execute(stmt)).scalar_one_or_none()
        return bool(result)
