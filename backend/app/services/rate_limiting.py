"""Per-session / per-user rate limiting (Redis-backed in :mod:`app.repositories.redis`).

Design §6 Decision 8 (*"10 messages + 1 document upload per guest session"*) and §7
(*"Per-session and per-tool rate limits in Redis"*) require throttling abuse while keeping
logged-in users on a far more generous budget. Two pieces live here, following the same
interface-before-implementation idiom as :class:`~app.services.cancellation.CancelRegistry`
/ :class:`~app.services.session_store.SessionStore`:

* :class:`RateLimiter` — the narrow **port** the service depends on: an atomic
  "increment a counter under ``key`` and tell me if it is still within ``limit``" over a
  fixed window. The **Redis-backed** adapter
  (:class:`~app.repositories.redis.RedisRateLimiter`) lives in the repository layer and
  satisfies this port; :class:`InMemoryRateLimiter` is the process-local test double.
* :class:`RateLimitService` — the **policy**: given the authenticated caller
  (:class:`~app.schemas.auth.CurrentUser`) and the action, it resolves the right key,
  limit and window (guest vs. user) and enforces it, raising :class:`RateLimitExceeded`
  when the caller is over budget.

The counter key is derived from the identity established at login (P3-01/P3-02): a guest is
keyed on its ``session_id`` (its whole identity), a logged-in user on its ``users.id`` — so
a guest cannot reset its budget by minting a new client id, and a user's limit follows them
across sessions.

.. warning::
   :class:`InMemoryRateLimiter` keeps counters in a process-local dict with no real TTL
   expiry. It is **not** suitable for production (not shared across workers, never resets):
   use :class:`~app.repositories.redis.RedisRateLimiter` in the real app.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from app.config import Settings, settings
from app.schemas.auth import CurrentUser


class RateLimitAction(StrEnum):
    """A rate-limited action. The value is used to namespace the Redis counter key."""

    MESSAGE = "message"
    UPLOAD = "upload"


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of a single :meth:`RateLimiter.hit`.

    ``count`` is the post-increment counter value; ``allowed`` is ``count <= limit``.
    ``retry_after_seconds`` is the counter's remaining TTL when denied (so the API can set a
    ``Retry-After`` header), or ``None`` when allowed / unknown.
    """

    allowed: bool
    count: int
    limit: int
    retry_after_seconds: int | None = None


class RateLimitExceeded(Exception):
    """Raised by :meth:`RateLimitService.enforce` when the caller is over budget.

    Carries the structured context the API layer needs to build a clear ``429`` response:
    which ``action`` was blocked, whether the caller is a guest (so the message can prompt
    upgrade-to-account), the ``limit`` they hit, and an optional retry hint.
    """

    def __init__(
        self,
        action: RateLimitAction,
        *,
        is_guest: bool,
        limit: int,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.action = action
        self.is_guest = is_guest
        self.limit = limit
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"rate limit exceeded for {action} (limit={limit}, guest={is_guest})")


class RateLimiter(ABC):
    """Atomic fixed-window counter port.

    Implementations own storage (process-local here, Redis in the repository layer);
    callers depend only on this interface (interface-before-implementation).
    """

    @abstractmethod
    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        """Increment the counter at ``key`` and report whether it is within ``limit``.

        The counter is created on the first hit of a window and expires after
        ``window_seconds`` (a fixed window), so the budget resets when the window lapses.
        """


class InMemoryRateLimiter(RateLimiter):
    """Process-local :class:`RateLimiter` — test double / interim default only.

    Not for production (single-process, never expires the window): use
    :class:`~app.repositories.redis.RedisRateLimiter` in the real app.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        allowed = count <= limit
        return RateLimitResult(
            allowed=allowed,
            count=count,
            limit=limit,
            retry_after_seconds=None if allowed else window_seconds,
        )


class RateLimitService:
    """Resolve and enforce the guest/user rate-limit policy (design §6.8 / §7).

    A thin policy over a :class:`RateLimiter`: it maps ``(caller, action)`` to the right
    counter key, limit and window and calls the limiter, translating an over-budget result
    into :class:`RateLimitExceeded`. All limits/windows are injected (via :meth:`from_settings`)
    so nothing reads the global ``settings`` in a method body.
    """

    def __init__(
        self,
        limiter: RateLimiter,
        *,
        guest_message_limit: int,
        guest_upload_limit: int,
        guest_window_seconds: int,
        user_message_limit: int,
        user_upload_limit: int,
        user_window_seconds: int,
    ) -> None:
        self._limiter = limiter
        self._guest_message_limit = guest_message_limit
        self._guest_upload_limit = guest_upload_limit
        self._guest_window_seconds = guest_window_seconds
        self._user_message_limit = user_message_limit
        self._user_upload_limit = user_upload_limit
        self._user_window_seconds = user_window_seconds

    @classmethod
    def from_settings(cls, limiter: RateLimiter, config: Settings = settings) -> RateLimitService:
        """Build from application config (guest caps + generous per-user window limits)."""
        return cls(
            limiter,
            guest_message_limit=config.GUEST_MAX_MESSAGES,
            guest_upload_limit=config.GUEST_MAX_UPLOADS,
            guest_window_seconds=config.GUEST_RATE_LIMIT_WINDOW_SECONDS,
            user_message_limit=config.USER_MAX_MESSAGES_PER_WINDOW,
            user_upload_limit=config.USER_MAX_UPLOADS_PER_WINDOW,
            user_window_seconds=config.USER_RATE_LIMIT_WINDOW_SECONDS,
        )

    def _policy(self, action: RateLimitAction, user: CurrentUser) -> tuple[str, int, int]:
        """Return ``(key, limit, window_seconds)`` for ``action`` and this caller.

        A guest is keyed on its ``session_id`` (its whole identity, so it cannot reset the
        budget by re-connecting); a logged-in user on its ``users.id`` (the limit follows the
        user across sessions). ``user_id`` is always set for ``role="user"`` (the JWT ``sub``);
        it falls back to ``session_id`` defensively so a malformed token can never key on an
        empty subject.
        """
        if user.role == "guest":
            subject = user.session_id
            window = self._guest_window_seconds
            limit = (
                self._guest_message_limit
                if action == RateLimitAction.MESSAGE
                else self._guest_upload_limit
            )
        else:
            subject = user.user_id or user.session_id
            window = self._user_window_seconds
            limit = (
                self._user_message_limit
                if action == RateLimitAction.MESSAGE
                else self._user_upload_limit
            )
        return f"{user.role}:{action}:{subject}", limit, window

    async def enforce(self, action: RateLimitAction, user: CurrentUser) -> RateLimitResult:
        """Count one ``action`` for ``user`` and raise if it puts them over budget.

        Returns the :class:`RateLimitResult` when within budget (so a caller can surface the
        remaining allowance); raises :class:`RateLimitExceeded` — carrying the guest flag and
        limit — when over, which the API maps to ``429`` with a clear, upgrade-prompting message.
        """
        key, limit, window = self._policy(action, user)
        result = await self._limiter.hit(key, limit=limit, window_seconds=window)
        if not result.allowed:
            raise RateLimitExceeded(
                action,
                is_guest=user.role == "guest",
                limit=limit,
                retry_after_seconds=result.retry_after_seconds,
            )
        return result
