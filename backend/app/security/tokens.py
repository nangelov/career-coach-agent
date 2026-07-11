"""Backend-owned session JWT codec (§6.2 / §7.1) — the one place tokens are minted/verified.

The design makes FastAPI the **session owner**: after a guest starts (P3-01) or a user
completes OIDC (P3-02), the backend mints *its own* short-lived session JWT and the Next.js
client sends it as a Bearer token. This module is that codec — a small, framework- and
datastore-free primitive so both auth entry points (and P3-02's FastAPI verify dependency)
share exactly one token shape and one signing path.

Kept deliberately narrow (encode + decode over :class:`SessionClaims`) and out of the
service layer: it holds no business logic and touches no datastore, so it is trivially
unit-testable and reusable. joserfc (Authlib's successor JOSE implementation, already a
transitive dependency) does the HS256 signing.

Token contract (claims):

* ``sub`` — subject: the ``users.id`` for a logged-in user (P3-02) or the session id for a
  guest (a guest has no user identity, so the session *is* the subject).
* ``role`` — ``"guest"`` | ``"user"`` (:data:`~app.schemas.auth.SessionRole`) — the single
  discriminator the app and frontend branch on.
* ``sid`` — the session id: the handle for server-side session state, chat memory, and the
  P3-04 guest rate-limit key. Distinct from ``sub`` so a logged-in token still names both
  the user and the concrete session.
* ``iat`` / ``exp`` — issued-at / expiry (unix seconds); ``exp`` enforces the short-lived
  posture from §7.1.

Secrets: the signing key comes only from settings (``JWT_SECRET_KEY`` → env / HF Space
Secret) — never hard-coded.
"""

from __future__ import annotations

import time

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey
from joserfc.jwt import JWTClaimsRegistry
from pydantic import BaseModel, ValidationError

from app.config import Settings, settings
from app.schemas.auth import SessionRole


class InvalidSessionToken(Exception):
    """Raised when a token fails signature/expiry validation or has malformed claims.

    P3-02's FastAPI verify dependency maps this to ``401 Unauthorized``; keeping a single
    codec-owned exception means callers never import joserfc's error types.
    """


class SessionClaims(BaseModel):
    """The validated payload of a session JWT (the codec's decode contract)."""

    sub: str
    role: SessionRole
    sid: str
    iat: int
    exp: int


class SessionTokenCodec:
    """Mint and verify backend session JWTs (HS256) — one shape for guest and user.

    Config is injected at construction (via :meth:`from_settings`) rather than read from
    the global ``settings`` inside methods, matching the repository/adapter convention.
    """

    def __init__(
        self,
        *,
        secret: str,
        algorithm: str = "HS256",
        expire_minutes: int = 60,
    ) -> None:
        if not secret:
            # Fail loudly at construction: an empty signing key would produce trivially
            # forgeable tokens. Required-with-no-default in settings, so this only trips
            # on a genuine misconfiguration.
            raise ValueError("JWT signing secret must not be empty")
        self._key = OctKey.import_key(secret)
        self._algorithm = algorithm
        self._expire_seconds = expire_minutes * 60

    @classmethod
    def from_settings(cls, config: Settings = settings) -> SessionTokenCodec:
        """Build from application config (signing key + algorithm + lifetime)."""
        return cls(
            secret=config.JWT_SECRET_KEY,
            algorithm=config.JWT_ALGORITHM,
            expire_minutes=config.JWT_EXPIRE_MINUTES,
        )

    @property
    def expires_in_seconds(self) -> int:
        """Bearer token lifetime in seconds (surfaced to the client as ``expires_in``)."""
        return self._expire_seconds

    def encode(self, *, sub: str, role: SessionRole, session_id: str) -> str:
        """Mint a signed session JWT for ``(sub, role, session_id)`` with iat/exp set."""
        issued_at = int(time.time())
        claims = {
            "sub": sub,
            "role": role,
            "sid": session_id,
            "iat": issued_at,
            "exp": issued_at + self._expire_seconds,
        }
        return jwt.encode({"alg": self._algorithm}, claims, self._key)

    def decode(self, token: str) -> SessionClaims:
        """Verify signature + expiry and return the typed claims.

        Raises :class:`InvalidSessionToken` on a bad signature, an expired/absent ``exp``,
        or claims that do not match :class:`SessionClaims` (e.g. an unknown ``role``).
        """
        try:
            decoded = jwt.decode(token, self._key, algorithms=[self._algorithm])
            # exp is essential — a token without an expiry must never validate.
            JWTClaimsRegistry(exp={"essential": True}).validate(decoded.claims)
            return SessionClaims.model_validate(decoded.claims)
        except (JoseError, ValidationError, ValueError) as exc:
            raise InvalidSessionToken(str(exc)) from exc
