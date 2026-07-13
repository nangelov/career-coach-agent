"""Pending-OIDC-transaction store seam (Redis-backed in :mod:`app.repositories.redis`).

The OIDC authorization-code + PKCE flow spans **two** stateless HTTP requests:
``GET /api/auth/login/{provider}`` starts it and ``GET /api/auth/callback/{provider}``
finishes it. Between them the backend must remember, per login attempt, the PKCE
``code_verifier`` (to complete the token exchange), the ``nonce``, and which provider the
flow was for — keyed by the opaque ``state`` value echoed back by the provider.

We deliberately keep this **server-side (Redis)** rather than in a signed cookie: the v2
auth model is Bearer-token-only (Next.js is a pure client, no ``SessionMiddleware`` /
``itsdangerous`` cookie) — so there is no cookie session to stash the transaction in. A
short-lived, single-use Redis record fits that model and doubles as CSRF protection (the
callback's ``state`` must match a record we issued).

Following the same interface-before-implementation idiom as
:class:`~app.services.session_store.SessionStore`: this module defines the narrow port the
auth service depends on plus a process-local implementation for tests / an interim default.
The **Redis-backed** implementation
(:class:`~app.repositories.redis.RedisOAuthStateStore`) lives in the repository layer.

.. warning::
   :class:`InMemoryOAuthStateStore` keeps records in a process-local dict with no real TTL
   expiry — a test double only, not production (lost on restart, not shared across workers).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, Field


class OAuthStateRecord(BaseModel):
    """The pending-login transaction persisted between ``/login`` and ``/callback``.

    Holds the per-attempt secrets the callback needs to complete the OIDC exchange. Never
    leaves the backend (it is keyed server-side by ``state``); the ``code_verifier`` in
    particular is the PKCE secret that must not be exposed to the browser.
    """

    provider: str = Field(..., min_length=1, max_length=32)
    code_verifier: str = Field(..., min_length=1, max_length=128)
    nonce: str = Field(..., min_length=1, max_length=128)
    redirect_uri: str = Field(..., min_length=1, max_length=512)
    created_at: datetime = Field(..., description="When the login attempt started (UTC).")
    upgrade_session_id: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Guest session id to carry over into the new account when this login is a "
            "guest→account upgrade (P3-03); resolved from a single-use upgrade ticket at "
            "``/login`` and consumed on ``/callback``. ``None`` for a plain login."
        ),
    )
    consent_policy_version: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "ToS + privacy policy version accepted on the login screen (§6.22), threaded "
            "through the OAuth redirect so the callback can record it against the ``users`` "
            "row (which does not exist yet at ``/login``). Set to "
            "``settings.CONSENT_POLICY_VERSION`` when the consent checkbox was ticked; the "
            "login is rejected before this record is written if consent was absent."
        ),
    )


class OAuthStateStore(ABC):
    """Persist / consume a pending OIDC login transaction keyed by its ``state``.

    Implementations own storage (process-local here, Redis in the repository layer);
    callers depend only on this interface (interface-before-implementation).
    """

    @abstractmethod
    async def put(self, state: str, record: OAuthStateRecord, *, ttl_seconds: int) -> None:
        """Store ``record`` under ``state``, expiring after ``ttl_seconds``."""

    @abstractmethod
    async def pop(self, state: str) -> OAuthStateRecord | None:
        """Return **and remove** the record for ``state`` (``None`` if absent/expired).

        Get-and-delete is atomic-by-contract: consuming a transaction is single-use, so a
        replayed ``state`` (or a double callback) cannot complete a second login.
        """


class InMemoryOAuthStateStore(OAuthStateStore):
    """Process-local :class:`OAuthStateStore` — test double / interim default only.

    Not for production (single-process, no restart survival, no real TTL): use
    :class:`~app.repositories.redis.RedisOAuthStateStore` in the real app.
    """

    def __init__(self) -> None:
        self._records: dict[str, OAuthStateRecord] = {}

    async def put(self, state: str, record: OAuthStateRecord, *, ttl_seconds: int) -> None:
        self._records[state] = record

    async def pop(self, state: str) -> OAuthStateRecord | None:
        return self._records.pop(state, None)
