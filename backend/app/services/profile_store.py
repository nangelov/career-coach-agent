"""Structured-profile read/write seam (Postgres-backed in :mod:`app.repositories.profile_store`).

``GET/PUT /api/profile`` (P5-05) let a logged-in user read the structured profile the P5-04
Celery task parsed from their CV and manually edit it — *without re-uploading a CV* (§4:
*"one structured CV/profile per user, reused across chats"*; §8 API table). Those two
endpoints need exactly two capabilities against the ``profiles`` table: fetch the caller's
profile and upsert it. That pair gets a narrow port here, following the
interface-before-implementation idiom used across the codebase (``UserStore``,
``FeedbackReader``, …): this module defines the port plus a process-local implementation for
tests; the **Postgres-backed** adapter
(:class:`~app.repositories.profile_store.PostgresProfileStore`) lives in the repository layer.

The port trades in :class:`~app.ingestion.profile.ProfileSchema` — the **authoritative**
structured shape (P5-03) the same Celery task already persists into the schema-less
``profiles.data`` JSONB column. Reusing it here (rather than redefining a parallel API shape)
keeps one source of truth for a profile's shape and means a read normalizes stored JSON back
through the same graceful-degradation validation the parse produced it with.

User-scoped by construction (§7 AuthZ): every method keys on the caller's ``users.id`` (the
verified token subject), so there is no path/query ``user_id`` a caller could tamper with — a
user only ever touches their own row.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.ingestion.profile import ProfileSchema


class ProfileStore(ABC):
    """Read / upsert a user's structured profile (§4 ``profiles.data`` JSONB, one row per user).

    Implementations own storage (process-local here, Postgres in the repository layer); the
    profile endpoints depend only on this interface. All access is keyed on ``users.id`` — the
    store never exposes a way to reach another user's row.
    """

    @abstractmethod
    async def get(self, user_id: str) -> ProfileSchema | None:
        """Return the user's structured profile, or ``None`` when they have none yet.

        ``None`` means "no ``profiles`` row" (the user never uploaded a CV) — distinct from a
        row whose parsed profile happens to be empty. Stored JSON is validated back through
        :class:`ProfileSchema`, so a partial/older document degrades gracefully into empty
        fields rather than raising. A malformed ``user_id`` resolves to ``None`` (fail-safe),
        never raises.
        """

    @abstractmethod
    async def upsert(self, user_id: str, profile: ProfileSchema) -> ProfileSchema:
        """Insert or replace the user's profile row (one per user), returning what was stored.

        Idempotent on ``users.id``: the first call creates the ``profiles`` row, later calls
        replace its ``data`` in place (keeping exactly one row per user). This is how a user
        manually edits their auto-parsed profile (P5-07). Returns the persisted
        :class:`ProfileSchema`.
        """


class InMemoryProfileStore(ProfileStore):
    """Process-local :class:`ProfileStore` — test double only.

    Keyed by ``users.id`` to mirror the DB's one-row-per-user (``unique`` on ``user_id``)
    constraint, so a test can assert cross-user isolation (user A's upsert never surfaces for
    user B). Not for production.
    """

    def __init__(self) -> None:
        self._by_user: dict[str, ProfileSchema] = {}

    async def get(self, user_id: str) -> ProfileSchema | None:
        return self._by_user.get(user_id)

    async def upsert(self, user_id: str, profile: ProfileSchema) -> ProfileSchema:
        self._by_user[user_id] = profile
        return profile
