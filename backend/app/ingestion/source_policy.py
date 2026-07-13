"""Shared crawl source-policy: robots.txt compliance + per-host rate limiting (design §10).

Any mining crawler in the app (market-intel job postings §5.6, learning-resource course
pages §5.7) must be a **polite** crawler: it respects a site's ``robots.txt`` and does not
hammer one host. This module owns that policy **once** so every crawler reuses it rather
than re-implementing it — the P6-06 learning-resource corpus imports the same
:class:`RobotsChecker` / :class:`HostRateLimiter` for course-provider crawls.

Deliberately **generic** — no market-intel-specific assumptions — so it is a clean shared
dependency. Two small pieces, no new heavy dependency (stdlib :mod:`urllib.robotparser`):

* :class:`RobotsChecker` — per-host ``robots.txt`` fetch + parse (cached for the run), then
  :meth:`RobotsChecker.can_fetch` answers "may I fetch this URL?". The actual network fetch
  is **injected** (an ``async`` callable) so the checker composes with the caller's
  **SSRF-guarded** client (design §7.2) rather than hand-rolling a second HTTP path or doing
  a blocking ``urllib`` fetch. A missing / unreadable ``robots.txt`` is treated as *allowed*
  (the web convention), a fetch that returns an explicit disallow blocks the URL.

* :class:`HostRateLimiter` — enforces a minimum interval between requests to the **same
  host** by sleeping the difference. The clock + sleep are injected so unit tests assert the
  wait deterministically without real time passing.

Both are intended for a **sequential** crawl loop (one bounded mining run); they keep a
tiny in-memory cache/marker per host keyed on ``scheme://host[:port]``.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

__all__ = [
    "DEFAULT_MIN_HOST_INTERVAL_SECONDS",
    "DEFAULT_USER_AGENT",
    "HostRateLimiter",
    "RobotsChecker",
    "host_key",
]

#: The crawler's advertised user-agent — the token ``robots.txt`` rules are matched against.
DEFAULT_USER_AGENT = "CareerCoachBot"

#: Default minimum seconds between two requests to the same host (polite crawl default).
DEFAULT_MIN_HOST_INTERVAL_SECONDS = 1.0

#: Async fetcher signature: given a URL, return its body text, or ``None`` on any failure
#: (missing file, non-200, transport / SSRF-guard rejection). The caller injects a fetcher
#: backed by its SSRF-guarded client so this module never opens its own network path.
RobotsFetcher = Callable[[str], Awaitable[str | None]]


def host_key(url: str) -> str:
    """The per-host cache/limit key for ``url`` — ``scheme://host[:port]`` (lower-cased host).

    Distinct schemes / ports are distinct hosts (a conservative, unambiguous key). Returns an
    empty string for a URL with no host (the caller treats that as un-fetchable).
    """
    parts = urlsplit(url)
    if not parts.hostname:
        return ""
    netloc = parts.hostname.lower()
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return f"{parts.scheme.lower()}://{netloc}"


class RobotsChecker:
    """Per-host ``robots.txt`` compliance check, cached for the run (design §10 source policy).

    Fetches ``<scheme>://<host>/robots.txt`` **once per host** through the injected
    :data:`RobotsFetcher` (the caller's SSRF-guarded client), parses it with the stdlib
    :class:`~urllib.robotparser.RobotFileParser`, and caches the parser so subsequent
    :meth:`can_fetch` calls for the same host are free. Fail-open on a missing/unreadable
    ``robots.txt`` (the standard convention) and fail-**closed** only on an explicit disallow.
    """

    def __init__(self, *, fetch: RobotsFetcher, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self._fetch = fetch
        self._user_agent = user_agent
        #: host_key → parsed rules, or ``None`` when the host has no usable ``robots.txt``.
        self._cache: dict[str, RobotFileParser | None] = {}

    async def can_fetch(self, url: str) -> bool:
        """Return whether ``url`` may be crawled under its host's ``robots.txt`` rules.

        A URL with no host is never fetchable. A host whose ``robots.txt`` is missing or
        unreadable is treated as fully allowed; otherwise the parsed rules decide.
        """
        key = host_key(url)
        if not key:
            return False
        parser = await self._parser_for(key)
        if parser is None:
            return True
        return parser.can_fetch(self._user_agent, url)

    async def _parser_for(self, key: str) -> RobotFileParser | None:
        """Return the cached (or freshly fetched + parsed) rules for host ``key``."""
        if key in self._cache:
            return self._cache[key]
        body = await self._fetch(f"{key}/robots.txt")
        parser: RobotFileParser | None = None
        if body is not None:
            parser = RobotFileParser()
            parser.parse(body.splitlines())
        self._cache[key] = parser
        return parser


class HostRateLimiter:
    """Enforce a minimum interval between requests to the same host (design §10).

    Sequential-crawl rate limiter: :meth:`acquire` sleeps just enough so two requests to the
    same host are at least ``min_interval_seconds`` apart, then records the host's last-request
    time. The monotonic ``clock`` and the ``sleep`` coroutine are injected so tests assert the
    computed wait without real elapsed time.
    """

    def __init__(
        self,
        *,
        min_interval_seconds: float = DEFAULT_MIN_HOST_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._interval = min_interval_seconds
        self._clock = clock
        self._sleep = sleep or _default_sleep
        self._last_request: dict[str, float] = {}

    async def acquire(self, url: str) -> None:
        """Wait (if needed) so this host is not hit more often than the configured interval."""
        key = host_key(url)
        if not key:
            return
        now = self._clock()
        last = self._last_request.get(key)
        if last is not None:
            wait = self._interval - (now - last)
            if wait > 0:
                await self._sleep(wait)
                now = self._clock()
        self._last_request[key] = now


async def _default_sleep(seconds: float) -> None:
    """Default async sleep (deferred import keeps this module import-light)."""
    import asyncio  # noqa: PLC0415

    await asyncio.sleep(seconds)
