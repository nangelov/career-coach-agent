"""Unit tests for the outbound-fetch SSRF guard (design §7.2, Risk table §10).

Covers every acceptance criterion for SEC-01:

* non-http(s) schemes are rejected (``file://`` / ``ftp://`` / ``gopher://``),
* a host that resolves to a private / loopback / link-local IP is rejected — including the
  cloud-metadata ``169.254.169.254`` and IPv4-mapped-IPv6 forms — using an **injected DNS
  resolver** (no real network),
* the compose-service deny-list (``localhost`` / ``db`` / ``redis`` / ``backend`` / ``*.internal``)
  is enforced before DNS,
* a redirect chain whose 2nd hop points at a private IP is rejected even though hop 1 was public
  (per-hop re-validation via the guarded transport),
* the redirect count is bounded,
* the response-size cap is enforced while streaming (not via ``Content-Length``),
* a happy-path public URL fetch succeeds through the guarded client.

No real network / DNS call is made: an ``httpx.MockTransport`` serves responses and a scripted
resolver drives the IP checks.
"""

from __future__ import annotations

import ipaddress
import threading
import time

import httpx
import pytest

from app.net.ssrf_guard import (
    GuardedTransport,
    SsrfError,
    build_guarded_client,
    read_capped,
    validate_url,
    validate_url_async,
)


def _resolver(mapping: dict[str, str]):
    """A ``Resolver`` double: map host → IP string (raises for an unknown host)."""

    def resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        if host not in mapping:
            raise OSError(f"no fake DNS entry for {host!r}")
        return [ipaddress.ip_address(mapping[host])]

    return resolve


PUBLIC = "93.184.216.34"


# --------------------------------------------------------------------------- #
# Scheme allow-list
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://example.com/x", "gopher://example.com", "data:text/plain,hi"],
)
def test_rejects_non_http_schemes(url: str) -> None:
    with pytest.raises(SsrfError):
        validate_url(url, resolver=_resolver({"example.com": PUBLIC}))


def test_allows_http_and_https_public_host() -> None:
    resolver = _resolver({"example.com": PUBLIC})
    validate_url("http://example.com/a", resolver=resolver)
    validate_url("https://example.com/a", resolver=resolver)  # no raise


# --------------------------------------------------------------------------- #
# Resolved-IP validation (mock DNS)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # RFC1918
        "192.168.1.10",  # RFC1918
        "172.16.0.1",  # RFC1918
        "169.254.169.254",  # link-local cloud metadata
        "100.64.0.1",  # CGNAT
        "0.0.0.0",  # unspecified
        "::1",  # IPv6 loopback
        "fd00::1",  # IPv6 unique-local
        "::ffff:10.0.0.1",  # IPv4-mapped-IPv6 private
    ],
)
def test_rejects_host_resolving_to_non_public_ip(ip: str) -> None:
    with pytest.raises(SsrfError):
        validate_url("https://evil.test/x", resolver=_resolver({"evil.test": ip}))


def test_rejects_literal_private_ip_without_dns() -> None:
    # A literal IP host is validated directly — the resolver must not even be consulted.
    def boom(_host: str):  # pragma: no cover - must not be called
        raise AssertionError("resolver should not run for a literal IP")

    with pytest.raises(SsrfError):
        validate_url("http://169.254.169.254/latest/meta-data/", resolver=boom)


def test_unresolvable_host_is_rejected() -> None:
    with pytest.raises(SsrfError):
        validate_url("https://nx.test/x", resolver=_resolver({}))


# --------------------------------------------------------------------------- #
# Async validation: DNS runs off the event loop + is bounded by a timeout
# --------------------------------------------------------------------------- #
async def test_async_validation_matches_sync_rejection() -> None:
    with pytest.raises(SsrfError):
        await validate_url_async(
            "https://evil.test/x", resolver=_resolver({"evil.test": "10.0.0.1"})
        )
    # public host passes without raising
    await validate_url_async("https://example.com/a", resolver=_resolver({"example.com": PUBLIC}))


async def test_async_validation_offloads_dns_to_worker_thread() -> None:
    """The blocking resolver must run off the event-loop thread, not inline on it."""
    main_thread = threading.get_ident()
    seen: list[int] = []

    def resolver(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        seen.append(threading.get_ident())
        return [ipaddress.ip_address(PUBLIC)]

    await validate_url_async("https://public.test/x", resolver=resolver)
    assert seen and seen[0] != main_thread


async def test_async_validation_times_out_on_hostile_dns() -> None:
    """A resolver that hangs must be cut off by the resolution timeout, not stall forever."""

    def slow_resolver(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        time.sleep(5)  # pragma: no cover - the timeout fires well before this returns
        return [ipaddress.ip_address(PUBLIC)]

    with pytest.raises(SsrfError):
        await validate_url_async(
            "https://slow.test/x", resolver=slow_resolver, resolution_timeout=0.05
        )


async def test_async_validation_skips_dns_for_literal_ip() -> None:
    def boom(_host: str):  # pragma: no cover - literal IP must not hit the resolver
        raise AssertionError("resolver should not run for a literal IP")

    with pytest.raises(SsrfError):
        await validate_url_async("http://169.254.169.254/latest/meta-data/", resolver=boom)


# --------------------------------------------------------------------------- #
# Host deny-list (before DNS)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "host", ["localhost", "db", "redis", "backend", "svc.internal", "node.local", "x.localhost"]
)
def test_rejects_denied_hosts_before_dns(host: str) -> None:
    def boom(_host: str):  # pragma: no cover - deny-list short-circuits before resolve
        raise AssertionError("resolver should not run for a denied host")

    with pytest.raises(SsrfError):
        validate_url(f"http://{host}/x", resolver=boom)


# --------------------------------------------------------------------------- #
# Redirect re-validation + bound (through a real guarded client)
# --------------------------------------------------------------------------- #
async def test_redirect_to_private_ip_is_rejected_on_second_hop() -> None:
    """Hop 1 (public) 302s to a private host — the guard must reject the followed hop."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public.test":
            return httpx.Response(302, headers={"location": "http://evil.test/steal"})
        return httpx.Response(200, text="should never be reached")  # pragma: no cover

    client = build_guarded_client(
        inner_transport=httpx.MockTransport(handler),
        resolver=_resolver({"public.test": PUBLIC, "evil.test": "169.254.169.254"}),
    )
    async with client:
        with pytest.raises(SsrfError):
            await client.get("http://public.test/start")


async def test_redirect_count_is_bounded() -> None:
    """An endless public→public redirect loop is cut off by the max-redirect cap."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://public.test/next"})

    client = build_guarded_client(
        inner_transport=httpx.MockTransport(handler),
        resolver=_resolver({"public.test": PUBLIC}),
        max_redirects=3,
    )
    async with client:
        with pytest.raises(httpx.TooManyRedirects):
            await client.get("http://public.test/start")


# --------------------------------------------------------------------------- #
# Response-size cap (streamed, not header-trusted)
# --------------------------------------------------------------------------- #
async def test_read_capped_aborts_oversized_body() -> None:
    big = b"x" * 10_000

    def handler(request: httpx.Request) -> httpx.Response:
        # Lie about Content-Length being small; the body is large — the cap must still bite.
        return httpx.Response(200, content=big, headers={"content-length": "5"})

    client = build_guarded_client(
        inner_transport=httpx.MockTransport(handler), resolver=_resolver({"public.test": PUBLIC})
    )
    async with client:
        async with client.stream("GET", "http://public.test/big") as response:
            body = await read_capped(response, max_bytes=1_000)
    assert len(body) <= 1_000


async def test_read_capped_returns_full_small_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"hello world")

    client = build_guarded_client(
        inner_transport=httpx.MockTransport(handler), resolver=_resolver({"public.test": PUBLIC})
    )
    async with client:
        async with client.stream("GET", "http://public.test/small") as response:
            body = await read_capped(response, max_bytes=1_000)
    assert body == b"hello world"


# --------------------------------------------------------------------------- #
# Happy-path public fetch through the guarded client
# --------------------------------------------------------------------------- #
async def test_happy_path_public_fetch_succeeds() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    client = build_guarded_client(
        inner_transport=httpx.MockTransport(handler), resolver=_resolver({"public.test": PUBLIC})
    )
    async with client:
        response = await client.get("http://public.test/ok")
    assert response.status_code == 200
    assert response.text == "ok"


async def test_guarded_transport_blocks_private_before_delegating() -> None:
    """The transport rejects a blocked target without ever calling the inner transport."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        calls.append(str(request.url))
        return httpx.Response(200)

    transport = GuardedTransport(
        httpx.MockTransport(handler), resolver=_resolver({"evil.test": "10.0.0.1"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SsrfError):
            await client.get("http://evil.test/x")
    assert calls == []
