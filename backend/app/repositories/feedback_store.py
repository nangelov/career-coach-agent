"""Postgres adapter for the :class:`~app.services.feedback.FeedbackReader` port.

Reads the free-text product feedback (§4 ``feedback`` table) that the admin-only
``GET /api/feedback`` endpoint returns — the v2 replacement for v1's per-day JSON files
served through ``GET /get-feedback?key=<HF_TOKEN>``.

Lives in the repository layer alongside the ORM model it maps; all DB access goes through
the shared :class:`~app.repositories.postgres.PostgresConnectionProvider` (§4) — no ad-hoc
engines/connections. Services/routers depend only on the ``FeedbackReader`` port, never on
this adapter or SQLAlchemy directly.
"""

from __future__ import annotations

from sqlalchemy import select

from app.repositories.models.identity import Feedback
from app.repositories.postgres import PostgresConnectionProvider
from app.schemas.feedback import FeedbackEntry
from app.services.feedback import FeedbackReader


class PostgresFeedbackReader(FeedbackReader):
    """Postgres-backed :class:`FeedbackReader` — list feedback newest-first (§4)."""

    def __init__(self, provider: PostgresConnectionProvider) -> None:
        self._provider = provider

    @classmethod
    def from_provider(cls, provider: PostgresConnectionProvider) -> PostgresFeedbackReader:
        """Build over the shared Postgres connection provider (§4)."""
        return cls(provider)

    async def list_feedback(self, *, limit: int) -> list[FeedbackEntry]:
        """Return the most-recent ``limit`` feedback rows (newest ``created_at`` first)."""
        stmt = (
            select(Feedback)
            .order_by(Feedback.created_at.desc(), Feedback.id.desc())
            .limit(max(1, limit))
        )
        async with self._provider.session() as db:
            rows = list((await db.execute(stmt)).scalars().all())
        return [
            FeedbackEntry(
                id=str(row.id),
                content=row.content,
                contact=row.contact,
                user_id=str(row.user_id) if row.user_id is not None else None,
                session_id=row.session_id,
                created_at=row.created_at,
            )
            for row in rows
        ]
