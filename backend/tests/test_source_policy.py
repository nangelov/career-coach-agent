"""Unit tests for the shared crawl source-policy (P6-04 / design §10).

Covers the two reusable pieces the mining crawlers depend on — ``robots.txt`` compliance and
per-host rate limiting — with injected fakes so no real network or clock is involved.
"""

from __future__ import annotations

from app.ingestion.source_policy import HostRateLimiter, RobotsChecker, host_key


# --------------------------------------------------------------------------- #
# host_key
# --------------------------------------------------------------------------- #
def test_host_key_normalizes_scheme_host_port() -> None:
    assert host_key("https://Example.com/jobs/123?utm=x") == "https://example.com"
    assert host_key("http://example.com:8080/a") == "http://example.com:8080"
    assert host_key("not a url") == ""


# --------------------------------------------------------------------------- #
# RobotsChecker
# --------------------------------------------------------------------------- #
class _Fetcher:
    """Records fetched URLs and returns a scripted robots.txt body per host (or None)."""

    def __init__(self, bodies: dict[str, str | None]) -> None:
        self._bodies = bodies
        self.calls: list[str] = []

    async def __call__(self, url: str) -> str | None:
        self.calls.append(url)
        return self._bodies.get(url)


async def test_robots_allows_when_no_robots_txt() -> None:
    fetcher = _Fetcher({"https://example.com/robots.txt": None})
    checker = RobotsChecker(fetch=fetcher)

    assert await checker.can_fetch("https://example.com/jobs/1") is True


async def test_robots_blocks_disallowed_path() -> None:
    body = "User-agent: *\nDisallow: /private/\n"
    fetcher = _Fetcher({"https://example.com/robots.txt": body})
    checker = RobotsChecker(fetch=fetcher)

    assert await checker.can_fetch("https://example.com/private/x") is False
    assert await checker.can_fetch("https://example.com/public/x") is True


async def test_robots_is_cached_per_host() -> None:
    body = "User-agent: *\nDisallow:\n"
    fetcher = _Fetcher({"https://example.com/robots.txt": body})
    checker = RobotsChecker(fetch=fetcher)

    await checker.can_fetch("https://example.com/a")
    await checker.can_fetch("https://example.com/b")

    # robots.txt fetched exactly once for the host despite two checks.
    assert fetcher.calls == ["https://example.com/robots.txt"]


async def test_robots_rejects_hostless_url() -> None:
    checker = RobotsChecker(fetch=_Fetcher({}))
    assert await checker.can_fetch("not-a-url") is False


# --------------------------------------------------------------------------- #
# HostRateLimiter
# --------------------------------------------------------------------------- #
class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


async def test_rate_limiter_sleeps_between_same_host_requests() -> None:
    clock = _Clock()
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.t += seconds  # advance the clock as if we waited

    limiter = HostRateLimiter(min_interval_seconds=2.0, clock=clock, sleep=fake_sleep)

    await limiter.acquire("https://example.com/a")  # first hit — no wait
    await limiter.acquire("https://example.com/b")  # same host, immediately → wait 2.0

    assert slept == [2.0]


async def test_rate_limiter_does_not_wait_across_different_hosts() -> None:
    clock = _Clock()
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:  # pragma: no cover - asserted empty
        slept.append(seconds)

    limiter = HostRateLimiter(min_interval_seconds=5.0, clock=clock, sleep=fake_sleep)

    await limiter.acquire("https://a.com/x")
    await limiter.acquire("https://b.com/x")

    assert slept == []
