"""Guest→account upgrade-ticket store seam (Redis-backed in :mod:`app.repositories.redis`).

Upgrading a guest to a logged-in account (P3-03) must carry the guest's *active* session
across the SSO round-trip, and it must do so **safely** — the server must never trust a
client-supplied guest id blindly (§4: *"Upgrade-to-account preserves current session"*).

The mechanism is a short-lived, single-use, opaque **upgrade ticket**:

* ``POST /api/auth/upgrade`` (guest-authenticated) mints a ticket bound *server-side* to the
  caller's verified guest ``session_id`` and hands the opaque ticket id back.
* The browser then navigates to ``GET /api/auth/login/{provider}?upgrade_ticket=<ticket>``.
  ``begin_login`` **consumes** the ticket (single-use), resolves it to the guest session id,
  and stashes that id in the server-side OAuth transaction — so the binding survives the
  provider round-trip without ever exposing the guest id (or a token) in a URL the browser
  could tamper with.

Because the ticket is server-minted, opaque, single-use and short-lived, a client can only
upgrade a guest session it actually holds a valid token for — closing the "trust a
client-supplied guest id" hole. It carries **only** the guest ``session_id`` (no secret).

Following the interface-before-implementation idiom of the sibling auth stores
(:class:`~app.services.session_store.SessionStore`,
:class:`~app.services.oauth_state_store.OAuthStateStore`): this module defines the narrow
port plus a process-local implementation for tests. The **Redis-backed** implementation
(:class:`~app.repositories.redis.RedisUpgradeTicketStore`) lives in the repository layer.

.. warning::
   :class:`InMemoryUpgradeTicketStore` keeps tickets in a process-local dict with no real
   TTL expiry — a test double only, not production (lost on restart, not shared across
   workers).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class UpgradeTicketStore(ABC):
    """Persist / consume a single-use guest→account upgrade ticket.

    Maps an opaque ticket id to the guest ``session_id`` it authorizes upgrading.
    Implementations own storage (process-local here, Redis in the repository layer);
    callers depend only on this interface (interface-before-implementation).
    """

    @abstractmethod
    async def put(self, ticket: str, guest_session_id: str, *, ttl_seconds: int) -> None:
        """Store ``guest_session_id`` under ``ticket``, expiring after ``ttl_seconds``."""

    @abstractmethod
    async def pop(self, ticket: str) -> str | None:
        """Return **and remove** the guest session id for ``ticket`` (``None`` if absent).

        Get-and-delete is single-use: a replayed ticket cannot authorize a second upgrade.
        """


class InMemoryUpgradeTicketStore(UpgradeTicketStore):
    """Process-local :class:`UpgradeTicketStore` — test double / interim default only.

    Not for production (single-process, no restart survival, no real TTL): use
    :class:`~app.repositories.redis.RedisUpgradeTicketStore` in the real app.
    """

    def __init__(self) -> None:
        self._tickets: dict[str, str] = {}

    async def put(self, ticket: str, guest_session_id: str, *, ttl_seconds: int) -> None:
        self._tickets[ticket] = guest_session_id

    async def pop(self, ticket: str) -> str | None:
        return self._tickets.pop(ticket, None)
