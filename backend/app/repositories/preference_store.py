"""Postgres adapter for the :class:`~app.services.preferences.PreferenceStore` port (P9-05).

Reads and upserts the explicit-preferences document (§4 ``preferences.data`` JSONB, one row per
user) that the memory panel (``GET /api/memory`` + ``PUT /api/memory/preferences``) serves — the
same row the recall step (P9-02, :mod:`app.agents.memory_agent`) reads to personalize a turn.

Lives in the repository layer alongside the ORM model it maps; all DB access goes through the
shared :class:`~app.repositories.postgres.PostgresConnectionProvider` (§4) — no ad-hoc engines.
Routers/services depend only on the ``PreferenceStore`` port, never on this adapter or SQLAlchemy
directly (§8 layering). Mirrors :class:`~app.repositories.profile_store.PostgresProfileStore`
(``profiles`` is the structurally identical one-JSONB-row-per-user table).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.repositories.models.identity import Preference
from app.repositories.postgres import PostgresConnectionProvider
from app.services.preferences import PreferenceStore


class PostgresPreferenceStore(PreferenceStore):
    """Postgres-backed :class:`PreferenceStore` — get / upsert on ``preferences`` (§4)."""

    def __init__(self, provider: PostgresConnectionProvider) -> None:
        self._provider = provider

    @classmethod
    def from_provider(cls, provider: PostgresConnectionProvider) -> PostgresPreferenceStore:
        """Build over the shared Postgres connection provider (§4)."""
        return cls(provider)

    async def get(self, user_id: str) -> dict[str, Any]:
        """Return the user's ``preferences.data``, or ``{}`` when no row exists / id is malformed.

        A single indexed lookup on the unique ``user_id``. A malformed id resolves to ``{}``
        (fail-safe) rather than raising, so an unknown caller reads as "no preferences".
        """
        try:
            uid = uuid.UUID(user_id)
        except ValueError:
            return {}
        stmt = select(Preference.data).where(Preference.user_id == uid)
        async with self._provider.session() as db:
            data = (await db.execute(stmt)).scalar_one_or_none()
        return data or {}

    async def upsert(self, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Insert or replace the user's preferences row atomically, returning what was stored.

        Uses ``INSERT ... ON CONFLICT (user_id) DO UPDATE`` so a first save creates the row and a
        later edit replaces its ``data`` in one round-trip — no SELECT-then-branch race, and
        exactly one row per user (the ``unique`` ``user_id``). ``updated_at`` is set explicitly on
        the conflict path because the ORM ``onupdate`` hook does not fire for a Core
        ``on_conflict_do_update``. The caller (:mod:`app.api.memory`) guarantees a real
        ``users.id`` — a guest is rejected upstream (no ``users`` row to anchor the FK).
        """
        stmt = (
            pg_insert(Preference)
            .values(user_id=uuid.UUID(user_id), data=data)
            .on_conflict_do_update(
                index_elements=[Preference.user_id],
                set_={"data": data, "updated_at": func.now()},
            )
        )
        async with self._provider.session() as db:
            await db.execute(stmt)
            await db.commit()
        return data
