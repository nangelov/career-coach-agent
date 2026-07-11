"""Unit tests for the backend session-JWT codec (P3-01).

Covers the token contract both auth entry points (guest here, SSO in P3-02) and the P3-02
verify dependency depend on: a signed round trip preserves the claims, an expired or
tampered token is rejected, an unknown role is rejected, and an empty signing secret fails
loudly at construction. No network / no datastore — the codec is a pure primitive.
"""

from __future__ import annotations

import time

import pytest
from joserfc import jwt
from joserfc.jwk import OctKey

from app.security.tokens import InvalidSessionToken, SessionTokenCodec

_SECRET = "unit-test-signing-secret-not-for-prod"


def _codec(expire_minutes: int = 60) -> SessionTokenCodec:
    return SessionTokenCodec(secret=_SECRET, algorithm="HS256", expire_minutes=expire_minutes)


def test_encode_decode_round_trip() -> None:
    codec = _codec()
    token = codec.encode(sub="sid-1", role="guest", session_id="sid-1")

    claims = codec.decode(token)
    assert claims.sub == "sid-1"
    assert claims.role == "guest"
    assert claims.sid == "sid-1"
    assert claims.exp > claims.iat


def test_expires_in_seconds_matches_lifetime() -> None:
    assert _codec(expire_minutes=15).expires_in_seconds == 900


def test_exp_is_lifetime_after_iat() -> None:
    codec = _codec(expire_minutes=30)
    claims = codec.decode(codec.encode(sub="u", role="user", session_id="s"))
    assert claims.exp - claims.iat == 30 * 60


def test_user_role_round_trips() -> None:
    codec = _codec()
    claims = codec.decode(codec.encode(sub="user-42", role="user", session_id="s9"))
    assert claims.role == "user"
    assert claims.sub == "user-42"


def test_expired_token_is_rejected() -> None:
    codec = _codec()
    # Mint a token that expired in the past (bypass encode's now-based exp).
    key = OctKey.import_key(_SECRET)
    now = int(time.time())
    expired = jwt.encode(
        {"alg": "HS256"},
        {"sub": "s", "role": "guest", "sid": "s", "iat": now - 100, "exp": now - 10},
        key,
    )
    with pytest.raises(InvalidSessionToken):
        codec.decode(expired)


def test_tampered_signature_is_rejected() -> None:
    codec = _codec()
    other = SessionTokenCodec(secret="a-different-secret", expire_minutes=60)
    token = other.encode(sub="s", role="guest", session_id="s")
    with pytest.raises(InvalidSessionToken):
        codec.decode(token)


def test_token_without_exp_is_rejected() -> None:
    codec = _codec()
    key = OctKey.import_key(_SECRET)
    no_exp = jwt.encode({"alg": "HS256"}, {"sub": "s", "role": "guest", "sid": "s"}, key)
    with pytest.raises(InvalidSessionToken):
        codec.decode(no_exp)


def test_unknown_role_is_rejected() -> None:
    codec = _codec()
    key = OctKey.import_key(_SECRET)
    now = int(time.time())
    bad_role = jwt.encode(
        {"alg": "HS256"},
        {"sub": "s", "role": "admin", "sid": "s", "iat": now, "exp": now + 60},
        key,
    )
    with pytest.raises(InvalidSessionToken):
        codec.decode(bad_role)


def test_empty_secret_fails_at_construction() -> None:
    with pytest.raises(ValueError):
        SessionTokenCodec(secret="", expire_minutes=60)


def test_garbage_token_is_rejected() -> None:
    with pytest.raises(InvalidSessionToken):
        _codec().decode("not-a-jwt")
