"""Auth request/response/domain models — guest sessions now, SSO in P3-02 (§7.1 / §9).

This module is the one authoritative contract for the auth surface the Next.js client
(P3-08) consumes. It intentionally covers **both** identity kinds up front so guest and
logged-in flows issue a *uniform* bearer token the frontend treats the same way:

* :data:`SessionRole` — ``"guest"`` vs ``"user"``; the single discriminator carried in the
  session JWT (:class:`~app.security.tokens.SessionClaims`) and every session record.
* :class:`SessionRecord` — the server-side session document persisted in Redis (guest) /
  Postgres-anchored (logged-in, P3-02). Shaped generically so P3-02 reuses it with a
  ``user_id`` set rather than inventing a second type.
* :class:`GuestSessionResponse` — the ``POST /api/auth/guest`` body: the bearer token plus
  the ``session_id`` the client keys subsequent chat/rate-limit calls on.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

#: The identity kind carried in a session JWT and every session record. ``"guest"`` is an
#: anonymous Redis-only session (no Postgres history — §4); ``"user"`` is a logged-in
#: identity (P3-02). Single home for the role literal so the token codec, the store, and
#: the API all agree on the vocabulary.
SessionRole = Literal["guest", "user"]


class SessionRecord(BaseModel):
    """The server-side session document (§4 ``sessions`` — id, user-or-guest, created).

    Persisted verbatim (JSON) in the session store. Generic across both identity kinds:
    a guest has ``role="guest"`` and ``user_id=None``; P3-02 sets ``role="user"`` +
    ``user_id`` for a logged-in session without needing a separate model. The
    ``session_id`` doubles as the Redis rate-limit key namespace for P3-04.
    """

    session_id: str = Field(..., min_length=1, max_length=64)
    role: SessionRole = "guest"
    user_id: str | None = Field(
        default=None,
        max_length=64,
        description="Logged-in users.id (P3-02); None for a guest session.",
    )
    created_at: datetime = Field(..., description="When the session was created (UTC).")
    consent_policy_version: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "ToS + privacy policy version accepted at session start (§6.22). For a guest, "
            "consent is per-session (guests hold nothing durable, §6.18) so it is stamped on "
            "this transient record for the life of the session — useful for support/debugging. "
            "For a logged-in user the durable record is on the ``users`` row; this mirror is "
            "optional. ``None`` on records that predate the consent gate."
        ),
    )


class GuestSessionRequest(BaseModel):
    """``POST /api/auth/guest`` body — the per-session consent acceptance (§6.22).

    A guest session is minted only when ``consent`` is ``true`` (the login screen's
    ToS/privacy checkbox). Guests hold nothing durable (§6.18), so consent is per-session:
    it is accepted afresh at **every** guest start. The body is optional on the wire (a
    missing body is treated as ``consent=false`` → rejected) so the endpoint fails closed.
    """

    consent: bool = Field(
        default=False,
        description="Whether the ToS + privacy notice was accepted (required to mint a session).",
    )


class GuestSessionResponse(BaseModel):
    """``POST /api/auth/guest`` response — the guest's bearer token + session handle.

    ``access_token`` is a backend-signed session JWT (role=``guest``) the client sends as
    ``Authorization: Bearer <token>`` on subsequent requests — the same shape P3-02 mints
    for logged-in users, so the frontend handles both uniformly. ``session_id`` is the
    stable handle the client passes to ``POST /api/chat`` and that P3-04 keys guest
    rate-limits on. ``expires_in`` is the token lifetime in seconds (JWT_EXPIRE_MINUTES).
    """

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    session_id: str
    role: SessionRole = "guest"
    expires_in: int = Field(..., description="Bearer token lifetime in seconds.")


class SessionResponse(BaseModel):
    """A minted session for a logged-in user (P3-02 SSO) — same shape as the guest body.

    Returned by the SSO login flow and mirrored, field-for-field, on
    :class:`GuestSessionResponse` so the Next.js client stores/sends **one** token shape
    for both identity kinds (§7.1). ``role`` is ``"user"`` here; ``session_id`` is the
    server-minted handle; ``expires_in`` is the JWT lifetime in seconds.
    """

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    session_id: str
    role: SessionRole = "user"
    expires_in: int = Field(..., description="Bearer token lifetime in seconds.")


class UpgradeTicketResponse(BaseModel):
    """``POST /api/auth/upgrade`` response — the short-lived guest→account upgrade ticket.

    ``upgrade_ticket`` is an opaque, single-use handle (no secret) the guest client appends
    to the SSO login URL (``GET /api/auth/login/{provider}?upgrade_ticket=...``) so the
    login carries the *current* guest session across to the new account (§4:
    *"Upgrade-to-account preserves current session"*). It is bound server-side to the
    verified guest ``session_id`` — the client never supplies a raw guest id. ``expires_in``
    is the ticket lifetime in seconds (short — it only needs to outlive the click-to-login).
    """

    upgrade_ticket: str
    expires_in: int = Field(..., description="Upgrade-ticket lifetime in seconds.")


class CurrentUser(BaseModel):
    """The authenticated caller resolved from a verified session JWT (the auth dependency).

    Produced by :class:`~app.services.auth.SessionAuthenticator` / the ``require_auth``
    FastAPI dependency and injected into every protected route. Uniform across identity
    kinds: a logged-in user has ``role="user"`` and ``user_id`` set to their ``users.id``;
    a guest has ``role="guest"`` and ``user_id=None`` (the ``session_id`` *is* their
    identity). ``session_id`` is the handle for server-side session state and the P3-04
    rate-limit key.
    """

    session_id: str
    role: SessionRole
    user_id: str | None = Field(
        default=None,
        description="Logged-in users.id (role=user); None for a guest.",
    )
