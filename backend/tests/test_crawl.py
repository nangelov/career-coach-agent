"""Unit tests for the shared polite-crawl transport (:mod:`app.ingestion.crawl`).

Drives the real SSRF-guarded fetch/robots helpers over an ``httpx.MockTransport`` (no real
network / DNS): HTML bodies are extracted to text, genuine ``text/plain`` is used verbatim,
``robots.txt`` keeps its line structure (so a ``Disallow`` is honored), the injected robots
fetcher is rate-limited, and any guard/transport failure fails soft to ``None``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.ingestion.crawl import (
    fetch_page_text,
    fetch_robots_body,
    guarded_robots_fetch,
)
from app.ingestion.source_policy import HostRateLimiter, RobotsChecker
from app.net.ssrf_guard import SsrfError, build_guarded_client
from tests.fakes import public_resolver


def _guarded_client(handler: Any) -> httpx.AsyncClient:
    return build_guarded_client(
        inner_transport=httpx.MockTransport(handler), resolver=public_resolver
    )


async def test_fetch_page_text_extracts_html() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html="<html><body><p>Learn  Kubernetes</p></body></html>")

    client = _guarded_client(handler)
    try:
        text = await fetch_page_text(client, "https://example.com/course")
    finally:
        await client.aclose()
    assert text == "Learn Kubernetes"


async def test_fetch_page_text_treats_plain_text_as_verbatim() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="Covers Python <and> RAG", headers={"content-type": "text/plain"}
        )

    client = _guarded_client(handler)
    try:
        text = await fetch_page_text(client, "https://example.com/p.txt")
    finally:
        await client.aclose()
    # ``<and>`` would be eaten by HTML extraction; plain text survives.
    assert text == "Covers Python <and> RAG"


async def test_fetch_page_text_fails_soft_on_ssrf() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        return httpx.Response(200, html="<p>x</p>")

    client = build_guarded_client(
        inner_transport=httpx.MockTransport(handler),
        resolver=public_resolver,
        deny_hosts={"example.com"},
    )
    try:
        with pytest.raises(SsrfError):
            async with client.stream("GET", "https://example.com/course"):
                pass
        assert await fetch_page_text(client, "https://example.com/course") is None
    finally:
        await client.aclose()


async def test_robots_body_preserves_line_structure() -> None:
    robots_txt = "User-agent: *\nDisallow: /private/\nAllow: /public/\n"

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=robots_txt, headers={"content-type": "text/plain"})

    client = _guarded_client(handler)
    try:
        body = await fetch_robots_body(client, "https://example.com/robots.txt")
    finally:
        await client.aclose()
    assert body is not None
    # Line structure intact (not whitespace-collapsed) — RobotFileParser needs it.
    assert "Disallow: /private/" in body.splitlines()


async def test_real_robots_checker_over_guarded_fetch_enforces_disallow() -> None:
    robots_txt = "User-agent: *\nDisallow: /private/\nAllow: /public/\n"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots_txt, headers={"content-type": "text/plain"})
        return httpx.Response(200, html="<p>a page</p>")

    client = _guarded_client(handler)
    checker = RobotsChecker(
        fetch=guarded_robots_fetch(client, HostRateLimiter(min_interval_seconds=0.0))
    )
    try:
        assert await checker.can_fetch("https://example.com/private/x") is False
        assert await checker.can_fetch("https://example.com/public/y") is True
    finally:
        await client.aclose()


async def test_guarded_robots_fetch_is_rate_limited() -> None:
    waits: list[float] = []

    async def _sleep(seconds: float) -> None:
        waits.append(seconds)

    # acquire reads the clock once (no wait) then, on the gated 2nd call, twice (before + after
    # the sleep): 1 + 2 = 3 reads for two same-host acquires.
    clock = iter([0.0, 0.0, 1.0])

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="User-agent: *\n", headers={"content-type": "text/plain"})

    limiter = HostRateLimiter(min_interval_seconds=1.0, clock=lambda: next(clock), sleep=_sleep)
    client = _guarded_client(handler)
    fetch = guarded_robots_fetch(client, limiter)
    try:
        await fetch("https://example.com/robots.txt")
        await fetch("https://example.com/robots.txt")
    finally:
        await client.aclose()
    # The second same-host robots fetch waited (the limiter gated it).
    assert waits == [1.0]
