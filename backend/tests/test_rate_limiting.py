"""Unit tests for the P3-04 rate-limit policy + Redis fixed-window counter.

Two layers, both with fakes — no real Redis:

* :class:`~app.services.rate_limiting.RateLimitService` policy: a guest is capped at 10
  messages + 1 upload per session (the 10th/1st ok, the 11th/2nd denied), keyed on the guest
  ``session_id``; a logged-in user gets a separate, more generous limit keyed on ``user_id``.
* :class:`~app.repositories.redis.RedisRateLimiter` against an in-memory ``FakeLimiterRedis``:
  ``INCR`` per hit, ``EXPIRE`` only on the first hit (fixed window), ``TTL`` for the
  retry-after hint.
"""

from __future__ import annotations

import pytest

from app.repositories.redis import RedisRateLimiter
from app.services.rate_limiting import (
    InMemoryRateLimiter,
    RateLimitAction,
    RateLimitExceeded,
    RateLimitService,
)
from tests.fakes import fake_current_user


def _service(
    *,
    guest_message_limit: int = 10,
    guest_upload_limit: int = 1,
    user_message_limit: int = 100,
    user_upload_limit: int = 20,
) -> RateLimitService:
    return RateLimitService(
        InMemoryRateLimiter(),
        guest_message_limit=guest_message_limit,
        guest_upload_limit=guest_upload_limit,
        guest_window_seconds=86_400,
        user_message_limit=user_message_limit,
        user_upload_limit=user_upload_limit,
        user_window_seconds=3600,
    )


# --------------------------------------------------------------------------- #
# Guest policy: 10 messages + 1 upload per session
# --------------------------------------------------------------------------- #
async def test_guest_message_limit_tenth_ok_eleventh_denied() -> None:
    service = _service(guest_message_limit=10)
    guest = fake_current_user("sess-guest", role="guest")

    for i in range(10):
        result = await service.enforce(RateLimitAction.MESSAGE, guest)
        assert result.allowed and result.count == i + 1

    with pytest.raises(RateLimitExceeded) as exc:
        await service.enforce(RateLimitAction.MESSAGE, guest)
    assert exc.value.is_guest is True
    assert exc.value.action == RateLimitAction.MESSAGE
    assert exc.value.limit == 10


async def test_guest_upload_limit_first_ok_second_denied() -> None:
    service = _service(guest_upload_limit=1)
    guest = fake_current_user("sess-guest", role="guest")

    ok = await service.enforce(RateLimitAction.UPLOAD, guest)
    assert ok.allowed and ok.count == 1

    with pytest.raises(RateLimitExceeded) as exc:
        await service.enforce(RateLimitAction.UPLOAD, guest)
    assert exc.value.is_guest is True
    assert exc.value.action == RateLimitAction.UPLOAD
    assert exc.value.limit == 1


async def test_guest_message_and_upload_budgets_are_independent() -> None:
    # Exhausting uploads must not consume the message budget (separate counters).
    service = _service(guest_message_limit=10, guest_upload_limit=1)
    guest = fake_current_user("sess-guest", role="guest")

    await service.enforce(RateLimitAction.UPLOAD, guest)
    with pytest.raises(RateLimitExceeded):
        await service.enforce(RateLimitAction.UPLOAD, guest)

    # Messages are still fully available.
    for _ in range(10):
        assert (await service.enforce(RateLimitAction.MESSAGE, guest)).allowed


async def test_two_guest_sessions_do_not_share_a_budget() -> None:
    service = _service(guest_message_limit=1)
    a = fake_current_user("sess-a", role="guest")
    b = fake_current_user("sess-b", role="guest")

    assert (await service.enforce(RateLimitAction.MESSAGE, a)).allowed
    # b has its own counter — a's exhaustion must not spill over.
    assert (await service.enforce(RateLimitAction.MESSAGE, b)).allowed
    with pytest.raises(RateLimitExceeded):
        await service.enforce(RateLimitAction.MESSAGE, a)


# --------------------------------------------------------------------------- #
# User policy: separate, more generous, keyed on user id
# --------------------------------------------------------------------------- #
async def test_user_limit_is_more_generous_and_keyed_on_user_id() -> None:
    service = _service(guest_message_limit=1, user_message_limit=3)
    user = fake_current_user("sess-1", role="user", user_id="user-1")

    # Far above the guest cap of 1 — the user tier applies, not the guest one.
    for _ in range(3):
        assert (await service.enforce(RateLimitAction.MESSAGE, user)).allowed
    with pytest.raises(RateLimitExceeded) as exc:
        await service.enforce(RateLimitAction.MESSAGE, user)
    assert exc.value.is_guest is False
    assert exc.value.limit == 3


async def test_user_budget_follows_user_across_sessions() -> None:
    # Same user, two different session ids → one shared counter (keyed on user_id).
    service = _service(user_message_limit=2)
    s1 = fake_current_user("sess-1", role="user", user_id="user-1")
    s2 = fake_current_user("sess-2", role="user", user_id="user-1")

    assert (await service.enforce(RateLimitAction.MESSAGE, s1)).allowed
    assert (await service.enforce(RateLimitAction.MESSAGE, s2)).allowed
    with pytest.raises(RateLimitExceeded):
        await service.enforce(RateLimitAction.MESSAGE, s1)


# --------------------------------------------------------------------------- #
# Redis fixed-window counter adapter
# --------------------------------------------------------------------------- #
class FakeLimiterRedis:
    """In-memory stand-in for the ``LimiterRedis`` seam (incr / expire / ttl)."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.expire_calls: list[tuple[str, int]] = []

    async def incr(self, name: str) -> int:
        self.counts[name] = self.counts.get(name, 0) + 1
        return self.counts[name]

    async def expire(self, name: str, time: int) -> bool:
        self.ttls[name] = time
        self.expire_calls.append((name, time))
        return True

    async def ttl(self, name: str) -> int:
        return self.ttls.get(name, -1)


async def test_redis_limiter_sets_expiry_only_on_first_hit() -> None:
    redis = FakeLimiterRedis()
    limiter = RedisRateLimiter(redis)

    r1 = await limiter.hit("guest:message:s1", limit=2, window_seconds=60)
    r2 = await limiter.hit("guest:message:s1", limit=2, window_seconds=60)

    assert r1.allowed and r1.count == 1
    assert r2.allowed and r2.count == 2
    # Fixed window: EXPIRE called exactly once (on the first hit), namespaced with the prefix.
    assert redis.expire_calls == [("ratelimit:guest:message:s1", 60)]


async def test_redis_limiter_denies_over_limit_with_retry_after() -> None:
    redis = FakeLimiterRedis()
    limiter = RedisRateLimiter(redis)

    await limiter.hit("k", limit=1, window_seconds=90)
    denied = await limiter.hit("k", limit=1, window_seconds=90)

    assert denied.allowed is False
    assert denied.count == 2
    # retry-after comes from the counter's remaining TTL.
    assert denied.retry_after_seconds == 90
