"""SEC block phase-exit verification (SEC-09) — cross-cutting security claims, end to end.

This is a **verification-only** module (no product code changed): it exercises the SEC-block
guarantees that no single prior SEC-0X task owned *end to end*, driving them through the **real**
code paths rather than a component's own unit tests.

The individual building blocks already have thorough coverage in their own suites:

* SSRF guard mechanics — ``test_ssrf_guard.py`` (scheme/IP/redirect/size checks in isolation).
* Untrusted-content fencing + injection inertness — ``test_untrusted_content.py`` (CV + crawled
  page + output net) and ``test_web_searcher.py`` (crawled instruction stays inert data).
* Contact-detail redaction through ``LLMRouter`` — ``test_llm_redaction.py``.
* Consent gate + token-free BFF session — ``test_auth_service.py`` / ``test_auth_api.py`` and the
  frontend ``bffSession`` suite.
* ``DELETE /api/me`` cascade — ``test_account_repository_postgres.py`` (live-DB) +
  ``test_me_api.py``.

What was **not** owned end to end, and is proven here, is that an SSRF probe is rejected when it
travels through the **actual crawler entrypoint**
(:func:`~app.agents.web_searcher.search_and_crawl`),
not only through the guard's own unit tests: a result URL that resolves to loopback /
link-local, and a public URL that 302-redirects into a private host, are both blocked — the
private target is never fetched — while the crawler still fails soft (the turn is not crashed and
the result is still cited). No real network / DNS call is made: an :class:`httpx.MockTransport`
serves canned responses and a scripted resolver drives the guard's IP checks.
"""

from __future__ import annotations

import ipaddress

import httpx

from app.agents.state import AgentState
from app.agents.web_searcher import search_and_crawl
from app.net.ssrf_guard import build_guarded_client
from tests.fakes import FakeSearchTool, web_result

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _resolver(mapping: dict[str, str]):
    """A ``Resolver`` double: map host → IP string (raises for an unknown host)."""

    def resolve(host: str) -> list[IPAddress]:
        if host not in mapping:
            raise OSError(f"no fake DNS entry for {host!r}")
        return [ipaddress.ip_address(mapping[host])]

    return resolve


def _state(message: str = "what is the AI job market like?") -> AgentState:
    return AgentState(session_id="s", user_message=message)


def _guarded_client(
    handler,
    mapping: dict[str, str],
    fetched: list[str] | None = None,
) -> httpx.AsyncClient:
    """A real SSRF-guarded client over a MockTransport + scripted DNS (records fetched URLs)."""

    def recording_handler(request: httpx.Request) -> httpx.Response:
        if fetched is not None:
            fetched.append(str(request.url))
        return handler(request)

    return build_guarded_client(
        inner_transport=httpx.MockTransport(recording_handler),
        resolver=_resolver(mapping),
    )


# --------------------------------------------------------------------------- #
# SSRF probes blocked through the REAL crawler entrypoint (search_and_crawl)
# --------------------------------------------------------------------------- #
async def test_crawler_blocks_loopback_target() -> None:
    """A search result URL resolving to loopback (127.0.0.1) is rejected by the crawler's guard."""
    tool = FakeSearchTool([web_result(url="http://loopback-probe.test/admin")])

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        raise AssertionError("loopback target was fetched — SSRF guard failed")

    served: list[str] = []
    client = _guarded_client(handler, {"loopback-probe.test": "127.0.0.1"}, fetched=served)
    async with client:
        result = await search_and_crawl(_state(), search_tool=tool, http_client=client)

    assert result.error is None
    assert len(result.citations) == 1  # still cited (fail-soft)
    assert result.data["crawled_count"] == 0  # but never fetched
    assert served == []  # inner transport never invoked for the loopback host


async def test_crawler_blocks_link_local_metadata_target() -> None:
    """A result URL resolving to the cloud metadata IP (169.254.169.254) is rejected."""
    tool = FakeSearchTool([web_result(url="http://metadata-probe.test/latest/meta-data/")])

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        raise AssertionError("link-local metadata target was fetched — SSRF guard failed")

    served: list[str] = []
    client = _guarded_client(handler, {"metadata-probe.test": "169.254.169.254"}, fetched=served)
    async with client:
        result = await search_and_crawl(_state(), search_tool=tool, http_client=client)

    assert result.error is None
    assert len(result.citations) == 1
    assert result.data["crawled_count"] == 0
    assert served == []


async def test_crawler_blocks_redirect_into_private_ip() -> None:
    """A public result URL that 302-redirects into a private host is rejected on the 2nd hop.

    Hop 1 (public) is fetched and returns a redirect to a private host; the guard re-validates the
    followed hop and rejects it, so the private target is never fetched — proven by the recorded
    fetch list containing only the public hop.
    """
    tool = FakeSearchTool([web_result(url="http://public-probe.test/start")])
    served: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public-probe.test":
            return httpx.Response(302, headers={"location": "http://evil-probe.test/steal"})
        # The private redirect target must never reach the inner transport.
        raise AssertionError(  # pragma: no cover - guard blocks the private hop first
            f"private redirect target {request.url} was fetched — SSRF guard failed"
        )

    client = _guarded_client(
        handler,
        {"public-probe.test": "93.184.216.34", "evil-probe.test": "169.254.169.254"},
        fetched=served,
    )
    async with client:
        result = await search_and_crawl(_state(), search_tool=tool, http_client=client)

    assert result.error is None
    assert len(result.citations) == 1  # fail-soft — turn not crashed
    assert result.data["crawled_count"] == 0  # redirect chain never yielded content
    # Only the public hop was ever fetched; the private redirect target was blocked.
    assert served == ["http://public-probe.test/start"]
    assert all(httpx.URL(u).host != "evil-probe.test" for u in served)


async def test_crawler_still_crawls_a_public_result_alongside_a_blocked_one() -> None:
    """A blocked SSRF probe is skipped per-URL while a legitimate public result still crawls.

    Proves the guard rejection is a *per-URL* fail-soft skip, not a whole-worker abort: the safe
    page's content still lands in the grounding bundle.
    """
    tool = FakeSearchTool(
        [
            web_result(title="Safe", url="http://safe-probe.test/guide"),
            web_result(title="Trap", url="http://loopback-probe.test/admin"),
        ]
    )
    served: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "safe-probe.test":
            return httpx.Response(200, html="<html><body><p>real career advice</p></body></html>")
        raise AssertionError(  # pragma: no cover - loopback host blocked before transport
            "loopback target was fetched — SSRF guard failed"
        )

    client = _guarded_client(
        handler,
        {"safe-probe.test": "93.184.216.34", "loopback-probe.test": "127.0.0.1"},
        fetched=served,
    )
    async with client:
        result = await search_and_crawl(_state(), search_tool=tool, http_client=client)

    assert result.error is None
    assert len(result.citations) == 2  # both results cited
    assert result.data["crawled_count"] == 1  # only the public one crawled
    assert result.content is not None
    assert "real career advice" in result.content
    assert served == ["http://safe-probe.test/guide"]  # loopback host never fetched
