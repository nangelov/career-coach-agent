"""User-account store seam (Postgres-backed in :mod:`app.repositories.user_store`).

When an OIDC login completes (P3-02), the backend must resolve the provider identity to a
row in the ``users`` table — creating it on first login, updating the mutable profile
fields (email / display name) on return visits — and get back the stable ``users.id`` the
session JWT will carry. That upsert is the only user-table access the auth flow needs, so
it gets a narrow port here.

SSO-only, no passwords (§7.1): a user is a ``(provider, sub)`` pair plus the minimal PII
the ``openid email profile`` scope yields (email, display name). No credential is ever
accepted or stored.

Following the interface-before-implementation idiom: this module defines the port the auth
service depends on plus a process-local implementation for tests. The **Postgres-backed**
implementation (:class:`~app.repositories.user_store.PostgresUserStore`) lives in the
repository layer and upserts on the ``uq_users_provider_sub`` constraint.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field


class UserAccount(BaseModel):
    """The resolved logged-in identity returned by an upsert.

    ``id`` is the ``users.id`` (string form of the UUID PK) that becomes the session JWT
    ``sub`` — the durable, provider-independent handle the rest of the app keys a user's
    data on. ``consent_policy_version`` / ``consent_accepted_at`` reflect the persisted
    consent gate (§6.22): the ToS + privacy policy version the user last accepted and when
    (``None`` for a row that predates a recorded consent).
    """

    id: str = Field(..., min_length=1, max_length=64)
    provider: str = Field(..., min_length=1, max_length=32)
    sub: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=1, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)
    consent_policy_version: str | None = Field(default=None, max_length=64)
    consent_accepted_at: datetime | None = Field(default=None)


class UserStore(ABC):
    """Resolve an OIDC identity to a ``users`` row (create-or-update), returning it.

    Implementations own storage (process-local here, Postgres in the repository layer);
    callers depend only on this interface. The one port for ``users``-table access, so the
    admin-authorization check (``is_admin``) lives here too rather than growing a second
    user-table adapter.
    """

    @abstractmethod
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
        """Insert the ``(provider, sub)`` identity or update its email/display name.

        Returns the persisted :class:`UserAccount` (with its stable ``id``). Idempotent:
        repeated logins for the same identity return the same ``id``.

        ``consent_policy_version`` / ``consent_accepted_at`` record the consent gate (§6.22):
        when supplied (every SSO login carries them), they are written on both insert and
        update, so a returning user re-accepting a bumped policy overwrites the stored
        version. Both default to ``None`` (columns are nullable) for callers that create a
        row outside the login flow (e.g. an out-of-band seed).
        """

    @abstractmethod
    async def is_admin(self, user_id: str) -> bool:
        """Return whether ``user_id`` (a ``users.id``) is flagged as an administrator (§7).

        Backs the ``require_admin`` dependency: an admin-only endpoint resolves the caller
        from their verified session JWT and then asks this. An unknown id returns ``False``
        (fail-closed) — never raises for a missing row.
        """


class InMemoryUserStore(UserStore):
    """Process-local :class:`UserStore` — test double only.

    Keyed by ``(provider, sub)`` to mirror the DB unique constraint; assigns a random id on
    first insert and refreshes the mutable fields on return. Not for production.
    """

    def __init__(self) -> None:
        self._by_identity: dict[tuple[str, str], UserAccount] = {}
        #: ``users.id`` values granted admin — tests populate this to exercise authz.
        self.admin_ids: set[str] = set()

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
        key = (provider, sub)
        existing = self._by_identity.get(key)
        account = UserAccount(
            id=existing.id if existing is not None else uuid4().hex,
            provider=provider,
            sub=sub,
            email=email,
            display_name=display_name,
            consent_policy_version=consent_policy_version,
            consent_accepted_at=consent_accepted_at,
        )
        self._by_identity[key] = account
        return account

    async def is_admin(self, user_id: str) -> bool:
        """Return whether ``user_id`` was granted admin (via :attr:`admin_ids`)."""
        return user_id in self.admin_ids
