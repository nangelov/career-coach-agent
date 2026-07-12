"""Postgres adapter for the :class:`~app.services.profile_store.ProfileStore` port.

Reads and upserts the structured profile document (§4 ``profiles.data`` JSONB, one row per
user) that ``GET/PUT /api/profile`` (P5-05) serve — the same row the P5-04 Celery task
writes after parsing a CV, so a manual edit and an auto-parse converge on one table.

Lives in the repository layer alongside the ORM model it maps; all DB access goes through the
shared :class:`~app.repositories.postgres.PostgresConnectionProvider` (§4) — no ad-hoc
engines/connections. Routers/services depend only on the ``ProfileStore`` port, never on this
adapter or SQLAlchemy directly (§8 layering).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.ingestion.profile import ProfileSchema
from app.repositories.models.identity import Profile
from app.repositories.postgres import PostgresConnectionProvider
from app.services.profile_store import ProfileStore


class PostgresProfileStore(ProfileStore):
    """Postgres-backed :class:`ProfileStore` — get / upsert on ``profiles`` (§4)."""

    def __init__(self, provider: PostgresConnectionProvider) -> None:
        self._provider = provider

    @classmethod
    def from_provider(cls, provider: PostgresConnectionProvider) -> PostgresProfileStore:
        """Build over the shared Postgres connection provider (§4)."""
        return cls(provider)

    async def get(self, user_id: str) -> ProfileSchema | None:
        """Return the user's structured profile, or ``None`` when no ``profiles`` row exists.

        A single indexed lookup on the unique ``user_id``. A malformed id resolves to ``None``
        (fail-safe) rather than raising, so an unknown caller reads as "no profile" instead of
        erroring. The stored JSONB is validated back through :class:`ProfileSchema` so an
        older/partial document degrades gracefully into empty fields.
        """
        try:
            uid = uuid.UUID(user_id)
        except ValueError:
            return None
        stmt = select(Profile.data).where(Profile.user_id == uid)
        async with self._provider.session() as db:
            data = (await db.execute(stmt)).scalar_one_or_none()
        if data is None:
            return None
        return ProfileSchema.model_validate(data)

    async def upsert(self, user_id: str, profile: ProfileSchema) -> ProfileSchema:
        """Insert or replace the user's profile row atomically, returning what was stored.

        Uses ``INSERT ... ON CONFLICT (user_id) DO UPDATE`` so a first save creates the row and
        a later edit replaces its ``data`` in one round-trip — no SELECT-then-branch race, and
        exactly one row per user (the ``unique`` ``user_id``). ``updated_at`` is set explicitly
        on the conflict path because the ORM ``onupdate`` hook does not fire for a Core
        ``on_conflict_do_update``. The caller (:mod:`app.api.profile`) guarantees a real
        ``users.id`` — a guest is rejected upstream (no ``users`` row to anchor the FK).
        """
        profile_data = profile.model_dump()
        stmt = (
            pg_insert(Profile)
            .values(user_id=uuid.UUID(user_id), data=profile_data)
            .on_conflict_do_update(
                index_elements=[Profile.user_id],
                set_={"data": profile_data, "updated_at": func.now()},
            )
        )
        async with self._provider.session() as db:
            await db.execute(stmt)
            await db.commit()
        return profile
