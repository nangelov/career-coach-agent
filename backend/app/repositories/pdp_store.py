"""Postgres adapter for the :class:`~app.services.pdp_store.PdpStore` port.

Inserts a generated Personal Development Plan into the ``pdps`` table (P2-05 schema): the
``career_goal`` + ``target_date`` + the structured ``content`` sections (as JSONB), which is
enough to re-render the styled PDF on demand without object storage (``pdf_path`` stays null
until an object-storage integration exists). ``POST /api/pdp`` (P7-03) writes one row per
generation, so a PDP is a first-class stored record P8's dashboard-seeding can later read.

Lives in the repository layer alongside the ORM model it maps; all DB access goes through the
shared :class:`~app.repositories.postgres.PostgresConnectionProvider` (§4) — no ad-hoc
engines/connections. Routers/services depend only on the ``PdpStore`` port, never on this
adapter or SQLAlchemy directly (§8 layering).
"""

from __future__ import annotations

import uuid
from datetime import date

from app.repositories.models.dashboard import Pdp
from app.repositories.postgres import PostgresConnectionProvider
from app.schemas.pdp import PdpContent
from app.services.pdp_store import PdpStore


class PostgresPdpStore(PdpStore):
    """Postgres-backed :class:`PdpStore` — insert a ``pdps`` row per generation (§4)."""

    def __init__(self, provider: PostgresConnectionProvider) -> None:
        self._provider = provider

    @classmethod
    def from_provider(cls, provider: PostgresConnectionProvider) -> PostgresPdpStore:
        """Build over the shared Postgres connection provider (§4)."""
        return cls(provider)

    async def save(
        self,
        *,
        user_id: str,
        career_goal: str,
        target_date: date | None,
        content: PdpContent,
    ) -> str:
        """Insert a new PDP row and return its generated id.

        The id is minted here so it can be returned without a round-trip. ``content`` is dumped
        to a plain JSON-safe dict for the ``pdps.content`` JSONB column (the same structured
        shape the agent produced and the PDF builder rendered). The caller
        (:mod:`app.api.pdp`) guarantees a real ``users.id`` — a guest is rejected upstream (no
        ``users`` row to anchor the ``user_id`` FK).
        """
        pdp_id = uuid.uuid4()
        row = Pdp(
            id=pdp_id,
            user_id=uuid.UUID(user_id),
            career_goal=career_goal,
            target_date=target_date,
            content=content.model_dump(mode="json"),
        )
        async with self._provider.session() as db:
            db.add(row)
            await db.commit()
        return pdp_id.hex
