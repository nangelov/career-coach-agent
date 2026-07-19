"""Explicit-preferences read/write seam (Postgres adapter in ``repositories.preference_store``).

The memory panel (``GET /api/memory`` + ``PUT /api/memory/preferences``, P9-05) needs exactly
two capabilities against the ``preferences`` table (§5.4 — one JSONB ``data`` row per user):
fetch the caller's explicit settings and upsert them. That pair gets a narrow port here,
following the interface-before-implementation idiom used across the codebase (``ProfileStore``,
``MessageFeedbackStore``, …): this module defines the port plus a process-local implementation
for tests; the **Postgres-backed** adapter
(:class:`~app.repositories.preference_store.PostgresPreferenceStore`) lives in the repository
layer.

The port trades in a plain ``dict`` (the schema-less ``preferences.data`` JSONB) rather than the
typed :class:`~app.schemas.memory.Preferences` model — the service owns the
validate/serialize boundary, keeping the store a thin data-access seam (the same split
``ProfileStore`` uses, only there the typed model *is* the stored shape). Every method keys on
the caller's ``users.id`` (the verified token subject), so there is no path/query ``user_id`` a
caller could tamper with — a user only ever touches their own row (§7 AuthZ).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PreferenceStore(ABC):
    """Read / upsert a user's explicit preferences (§4 ``preferences.data`` JSONB, one per user).

    Implementations own storage (process-local here, Postgres in the repository layer); the
    memory service depends only on this interface. All access is keyed on ``users.id`` — the
    store never exposes a way to reach another user's row.
    """

    @abstractmethod
    async def get(self, user_id: str) -> dict[str, Any]:
        """Return the user's stored ``preferences.data``, or ``{}`` when they have no row yet.

        Empty dict (not ``None``) means "no preferences saved" — the friendlier read contract
        for a panel that always renders a (possibly empty) settings form. A malformed
        ``user_id`` resolves to ``{}`` (fail-safe), never raises.
        """

    @abstractmethod
    async def upsert(self, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Insert or replace the user's preferences row (one per user), returning what was stored.

        Idempotent on ``users.id``: the first call creates the ``preferences`` row, later calls
        replace its ``data`` in place. This is how a user edits their explicit settings. Returns
        the persisted document.
        """


class InMemoryPreferenceStore(PreferenceStore):
    """Process-local :class:`PreferenceStore` — test double only.

    Keyed by ``users.id`` to mirror the DB's one-row-per-user (``unique`` on ``user_id``)
    constraint, so a test can assert cross-user isolation. Not for production.
    """

    def __init__(self) -> None:
        self._by_user: dict[str, dict[str, Any]] = {}

    async def get(self, user_id: str) -> dict[str, Any]:
        return dict(self._by_user.get(user_id, {}))

    async def upsert(self, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self._by_user[user_id] = dict(data)
        return dict(data)
