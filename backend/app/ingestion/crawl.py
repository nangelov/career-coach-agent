"""Shared polite-crawl transport: SSRF-guarded page + ``robots.txt`` fetch (design §7.2 / §10).

Every mining crawler in the app (market-intel job postings §5.6, learning-resource course
pages §5.7) needs the same small transport layer on top of the one **SSRF-guarded client**
(:func:`~app.net.ssrf_guard.build_guarded_client`): fetch a URL with a byte/timeout cap,
decode it, and — for page text — collapse it to plain text; for ``robots.txt`` keep the body
**line-structured** so :class:`~urllib.robotparser.RobotFileParser` can parse it. This module
owns those helpers **once** so a second crawler reuses them rather than re-deriving the (subtle)
robots-fetch handling.

Three fail-soft primitives, all over an injected :class:`httpx.AsyncClient` (the caller's
SSRF-guarded client — never a raw client):

* :func:`fetch_decoded` — one SSRF-guarded, byte/timeout-capped GET → ``(decoded_body,
  content_type)`` with the body **verbatim** (line structure preserved). Fail-soft: a timeout,
  bad status, or :class:`~app.net.ssrf_guard.SsrfError` (private target / unsafe redirect) is
  swallowed and yields ``None`` — a single untrusted fetch never crashes the miner.
* :func:`fetch_page_text` — :func:`fetch_decoded` + HTML→text extraction for ``text/html``
  bodies (genuine ``text/plain`` is used as-is, **not** HTML-stripped) + a final whitespace
  collapse: the bounded plain text an extraction LLM sees.
* :func:`guarded_robots_fetch` — builds the rate-limited ``robots.txt`` fetcher a
  :class:`~app.ingestion.source_policy.RobotsChecker` injects. The body is returned **without**
  whitespace-collapse / HTML strip (doing either mashes every rule onto one line and silently
  drops every ``Disallow``) and each fetch is gated by the **same** per-host rate limiter as
  page fetches (polite — no back-to-back host hits).

.. note::
   :mod:`app.agents.market_agent` predates this module and still carries equivalent private
   copies of these helpers; consolidating it onto this shared module is a follow-up (out of
   scope for the task that introduced this file, which must not modify the market pipeline).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from app.ingestion.html_text import html_to_text
from app.net.ssrf_guard import SsrfError, read_capped

if TYPE_CHECKING:
    import httpx

    from app.ingestion.source_policy import HostRateLimiter

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_CRAWL_MAX_BYTES",
    "DEFAULT_CRAWL_TIMEOUT_SECONDS",
    "fetch_decoded",
    "fetch_page_text",
    "fetch_robots_body",
    "guarded_robots_fetch",
]

#: Per-page crawl timeout / byte cap (bounds one slow or huge page). Matches the market
#: pipeline's tunables so both crawlers are equally polite/bounded.
DEFAULT_CRAWL_TIMEOUT_SECONDS = 8.0
DEFAULT_CRAWL_MAX_BYTES = 1_500_000


async def fetch_decoded(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = DEFAULT_CRAWL_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_CRAWL_MAX_BYTES,
) -> tuple[str, str] | None:
    """Fetch one URL (SSRF-guarded, byte/timeout-capped) → ``(decoded_body, content_type)``.

    Returns the body **verbatim** (line structure preserved) so line-oriented formats like
    ``robots.txt`` survive intact; higher-level helpers apply HTML extraction / whitespace
    collapse as appropriate. Fail-soft: a timeout, bad status, or an
    :class:`~app.net.ssrf_guard.SsrfError` (private target / unsafe redirect) is caught and
    yields ``None`` — a single untrusted fetch never crashes the caller.
    """
    try:
        async with client.stream("GET", url, timeout=timeout) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            raw = await read_capped(response, max_bytes=max_bytes)
            encoding = response.charset_encoding or "utf-8"
    except SsrfError as exc:
        logger.info("SSRF guard blocked crawl of %s: %s", url, exc)
        return None
    except Exception as exc:
        logger.warning("crawl failed for %s: %s", url, exc)
        return None
    return raw.decode(encoding, errors="replace"), content_type


async def fetch_page_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = DEFAULT_CRAWL_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_CRAWL_MAX_BYTES,
) -> str | None:
    """Fetch one page → its bounded, whitespace-collapsed plain-text extract, or ``None``.

    HTML bodies are run through :func:`~app.ingestion.html_text.html_to_text`; genuine
    ``text/plain`` bodies are already plain and used as-is (no misapplied HTML extraction). A
    final whitespace collapse normalizes the result for downstream extraction. Fail-soft (see
    :func:`fetch_decoded`).
    """
    fetched = await fetch_decoded(client, url, timeout=timeout, max_bytes=max_bytes)
    if fetched is None:
        return None
    decoded, content_type = fetched
    text = html_to_text(decoded) if "html" in content_type else decoded
    return " ".join(text.split()) or None


async def fetch_robots_body(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = DEFAULT_CRAWL_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_CRAWL_MAX_BYTES,
) -> str | None:
    """Fetch a ``robots.txt`` → its body with **line structure preserved**, or ``None``.

    :class:`~urllib.robotparser.RobotFileParser` parses line-by-line, so — unlike page text —
    the body must **not** be whitespace-collapsed or HTML-stripped (doing so mashes every rule
    onto one line and silently drops every ``Disallow``). ``None`` means "no usable robots.txt",
    which the :class:`~app.ingestion.source_policy.RobotsChecker` treats as fail-open (the web
    convention).
    """
    fetched = await fetch_decoded(client, url, timeout=timeout, max_bytes=max_bytes)
    return fetched[0] if fetched is not None else None


def guarded_robots_fetch(
    client: httpx.AsyncClient,
    limiter: HostRateLimiter,
    *,
    timeout: float = DEFAULT_CRAWL_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_CRAWL_MAX_BYTES,
) -> Callable[[str], Awaitable[str | None]]:
    """Build the default rate-limited ``robots.txt`` fetcher over the SSRF-guarded ``client``.

    Wraps :func:`fetch_robots_body` so each ``robots.txt`` request (fetched once per host on a
    cache miss) is gated by the **same** per-host rate limiter as page fetches — the robots
    fetch and the following page fetch are not hit back-to-back.
    """

    async def _fetch(url: str) -> str | None:
        await limiter.acquire(url)
        return await fetch_robots_body(client, url, timeout=timeout, max_bytes=max_bytes)

    return _fetch
