"""Account lifecycle service — GDPR erasure + export (§7.6 / §9).

``DELETE /api/me`` (Art. 17 right to erasure) and ``GET /api/me/export`` (Art. 20 portability)
are **logged-in-user only** — a guest has nothing durable to erase or export (their only state
is a Redis session record that self-expires on TTL, §4/§6.18). The single collaborator here,
:class:`AccountService`, orchestrates the two-store operation an erasure needs while depending
only on **ports** (no datastore driver, §8 Router → Service → Repository):

* an :class:`AccountRepository` (Postgres-backed in the repository layer) for the durable
  footprint — deleting the ``users`` row (which **cascades** the whole Postgres footprint via
  the P2 ``ondelete="CASCADE"`` FKs) and assembling the export;
* a :class:`~app.services.session_store.SessionStore` (Redis-backed) to enumerate **and** revoke
  the user's live sessions across **all** devices. The session store is the *authoritative*
  registry of live sessions (a session exists there from login, before any Postgres ``sessions``
  row is lazily written), so "every device" is enumerated from its per-user index — not from the
  Postgres ``sessions`` table, which would miss a just-logged-in device that has not yet chatted.

Erasure is **idempotent**: erasing an unknown/already-deleted user enumerates no sessions and
deletes zero rows — never a 500 (§ acceptance criteria).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.account import AccountExport
from app.services.session_store import SessionStore


class AccountRepository(ABC):
    """Durable (Postgres) side of account erasure/export — one narrow port (§8).

    Implementations own storage (process-local double here, Postgres in the repository
    layer); :class:`AccountService` depends only on this interface. Every method is keyed on
    the caller's ``users.id`` — there is no way to reach another user's rows.
    """

    @abstractmethod
    async def delete_user(self, user_id: str) -> None:
        """Delete the ``users`` row for ``user_id``, cascading its whole footprint (§4/§7.6).

        Idempotent: deleting an unknown/already-deleted id removes zero rows and does not
        raise. A malformed id is a no-op.
        """

    @abstractmethod
    async def export(self, user_id: str) -> AccountExport:
        """Assemble the caller's complete data export (Art. 20, §7.6).

        Strictly scoped to ``user_id`` and excludes raw embedding vectors (see
        :mod:`app.schemas.account`). A malformed/unknown id yields an empty export.
        """


class AccountService:
    """Erase or export a logged-in user's data across every store (§7.6).

    Ports are injected at construction — the durable :class:`AccountRepository` and the Redis
    :class:`SessionStore` — so the service touches no driver directly and is unit-testable with
    fakes. Callers (the router) pass the **verified** token subject's own ``user_id``; this
    service never accepts a client-supplied id.
    """

    def __init__(self, repo: AccountRepository, sessions: SessionStore) -> None:
        self._repo = repo
        self._sessions = sessions

    async def erase(self, user_id: str) -> None:
        """Revoke the user's live sessions, then delete their Postgres footprint (Art. 17).

        Sessions are enumerated from the **authoritative** Redis session store (its per-user
        index), not the lazily-populated Postgres ``sessions`` table — so *every* device is
        revoked, including a freshly-logged-in one that has not yet persisted a chat turn (and
        therefore has no Postgres row). Each Redis session record is deleted so a still-
        unexpired JWT on any device stops resolving immediately. The Postgres delete then
        cascades profile, preferences, conversations, messages, feedback, KB docs/chunks,
        memories, PDPs and dashboard rows in one statement. Idempotent end-to-end.
        """
        for session_id in await self._sessions.list_user_sessions(user_id):
            await self._sessions.delete(session_id)
        await self._repo.delete_user(user_id)

    async def export(self, user_id: str) -> AccountExport:
        """Return the caller's complete, own-only data export (Art. 20)."""
        return await self._repo.export(user_id)


class InMemoryAccountRepository(AccountRepository):
    """Process-local :class:`AccountRepository` — test double only.

    Lets a test script a user's export payload and assert that an erase deletes the user (the
    session-revocation side is exercised through the :class:`SessionStore`). Not for production.
    """

    def __init__(self) -> None:
        #: user_id → its export payload (seed to exercise the export contract).
        self.exports_by_user: dict[str, AccountExport] = {}
        #: user ids passed to :meth:`delete_user`, in order (assert idempotency/deletion).
        self.deleted: list[str] = []

    async def delete_user(self, user_id: str) -> None:
        self.deleted.append(user_id)
        self.exports_by_user.pop(user_id, None)

    async def export(self, user_id: str) -> AccountExport:
        return self.exports_by_user.get(user_id, AccountExport())
