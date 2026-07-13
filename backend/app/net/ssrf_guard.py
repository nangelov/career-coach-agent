"""SSRF guard for outbound crawler / tool fetches (design §7.2, Risk table §10).

Every outbound fetch that targets an **externally-supplied / attacker-influenceable URL**
(a crawled search-result page, a URL extracted from a document, an LLM tool-call argument)
MUST go through this guard. Fetches to our own fixed, hard-coded internal services
(Postgres / Redis / the HF inference endpoint via their SDKs) are *not* in scope — those
are not attacker-controlled.

**The threat.** Without a guard, a crawled page can ``302`` the fetcher into the co-located
``redis:6379`` / ``db:5432`` or a cloud metadata endpoint (``169.254.169.254``), turning the
crawler into a Server-Side Request Forgery proxy. v1's ``follow_redirects=True`` with no
validation is exactly this hole — the highest-severity code gap called out in the design.

**What the guard enforces** (all four, per design §7.2):

1. **Scheme allow-list** — ``http`` / ``https`` only. ``file://``, ``ftp://``, ``gopher://``
   and everything else are rejected.
2. **Resolved-IP validation** — the hostname is resolved and every resolved address must be
   *publicly routable*. Private (RFC1918), loopback, link-local (incl. the cloud-metadata
   ``169.254.169.254``), multicast, reserved, CGNAT, TEST-NET, and IPv4-mapped-IPv6 forms of
   any of those are rejected. The check runs against the **resolved IP**, not just the literal
   hostname string.
3. **Bounded redirects, re-validated per hop** — the guard is an :class:`httpx.AsyncBaseTransport`
   wrapper, so httpx re-invokes it for *every* redirect hop; each hop's target URL passes the
   full scheme + host + resolved-IP check before it is followed, and the client caps the hop
   count at :data:`MAX_REDIRECTS`. There is no blind ``follow_redirects=True``.
4. **Host allow/deny list** — a deny-list (``localhost`` and the compose service names
   ``db`` / ``redis`` / ``backend``, plus ``*.internal`` / ``*.local`` / ``*.localhost``
   suffixes) is enforced *before* DNS even runs. The structure leaves room for a future
   allow-list of trusted course/market-intel domains (P6) — see :func:`validate_url`'s
   ``deny_hosts`` seam — without over-building that logic now.

**DNS-rebinding posture.** The guard uses the transport-hook option the design offers
("*use an httpx transport hook that validates the socket's peer address*"): it validates the
resolved IP on **every** hop, so a redirect that resolves to a private IP is rejected even if
the first hop was public. A literal-IP host is validated directly (no DNS). The residual
TOCTOU window between our resolution and httpx's own connect is inherent to not pinning the
socket; pinning would require rewriting the request to the IP and breaking TLS SNI/cert
validation, which is a worse trade for a career-coach crawler. The per-hop resolved-IP check
is the design-sanctioned mitigation.

**Event-loop hygiene.** DNS resolution (blocking ``getaddrinfo``) is never run directly on the
event loop from the async transport path — :func:`validate_url_async` offloads it to a worker
thread under an explicit :data:`RESOLUTION_TIMEOUT_SECONDS` bound. The crawler runs as an async
LangGraph node in the SSE request path, so a slow/hostile DNS server for an attacker-influenced
host cannot stall other concurrent user streams. The synchronous :func:`validate_url` remains
for direct/sync callers and tests (fast injected resolvers); the transport always uses the async
variant.

**Response-size cap.** :func:`read_capped` streams the body and aborts once the byte cap is
exceeded — it never trusts a ``Content-Length`` header (which can lie).

**Test seam.** DNS resolution is injected (``resolver``) so tests exercise private-IP / rebind
rejection without real DNS, and the inner transport is injected (``inner_transport``) so tests
serve canned responses through a real guarded client (``httpx.MockTransport``). No real network
call is ever made in tests.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Callable, Iterable, Sequence
from typing import Final

import anyio
import httpx

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_DENY_HOSTS",
    "DEFAULT_DENY_SUFFIXES",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "MAX_REDIRECTS",
    "GuardedTransport",
    "Resolver",
    "SsrfError",
    "build_guarded_client",
    "default_resolver",
    "read_capped",
    "validate_url",
    "validate_url_async",
]

#: The only URL schemes an outbound fetch may use.
ALLOWED_SCHEMES: Final = frozenset({"http", "https"})

#: Exact hostnames that are always denied (loopback alias + compose service names). The
#: co-located ``db`` / ``redis`` / ``backend`` names are the SSRF pivot targets §7.2 warns of.
DEFAULT_DENY_HOSTS: Final[frozenset[str]] = frozenset({"localhost", "db", "redis", "backend"})

#: Hostname suffixes that are always denied (internal service naming conventions).
DEFAULT_DENY_SUFFIXES: Final[tuple[str, ...]] = (".internal", ".local", ".localhost")

#: Hard cap on redirect hops the guarded client follows (each hop is re-validated).
MAX_REDIRECTS: Final = 5

#: Default hard cap on bytes read from one response body (streamed enforcement).
DEFAULT_MAX_RESPONSE_BYTES: Final = 2_000_000

#: Default connect / read timeouts for the guarded client (bounds a slow host).
CONNECT_TIMEOUT_SECONDS: Final = 5.0
READ_TIMEOUT_SECONDS: Final = 8.0

#: Bound (seconds) on a single hostname resolution when run off the event loop. A hostile DNS
#: server for an attacker-influenced host cannot stall a request longer than this.
RESOLUTION_TIMEOUT_SECONDS: Final = 5.0

#: A resolved IP address (v4 or v6).
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

#: Hostname → resolved IPs. Injected so tests can drive rejection without real DNS.
Resolver = Callable[[str], Sequence[IPAddress]]


class SsrfError(Exception):
    """Raised when an outbound fetch target fails the SSRF guard.

    Message text is intentionally coarse (scheme / host / address family) and never echoes
    which internal target the attacker probed — it is caller-facing only as a fail-soft skip
    reason, not user-facing content.
    """


def default_resolver(host: str) -> list[IPAddress]:
    """Resolve ``host`` to its IP addresses via the stdlib (no new dependency).

    Returns every address ``getaddrinfo`` yields (both A and AAAA), so validation rejects a
    host that resolves to *any* non-public address. Raises :class:`OSError` /
    :class:`socket.gaierror` on resolution failure, which :func:`validate_url` maps to an
    :class:`SsrfError`.
    """
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [ipaddress.ip_address(info[4][0]) for info in infos]


def _normalize(ip: IPAddress) -> IPAddress:
    """Unwrap an IPv4-mapped IPv6 address (``::ffff:a.b.c.d``) to its IPv4 form.

    Prevents bypassing the IPv4 private/link-local checks by expressing the same address as a
    mapped IPv6 literal.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _is_blocked_ip(ip: IPAddress) -> bool:
    """True if ``ip`` is anything other than a publicly-routable address.

    ``is_global`` alone rejects private / loopback / link-local / CGNAT / TEST-NET / reserved
    ranges; the explicit predicates are kept as defense-in-depth and to make the intent (and
    the design's exact wording) legible.
    """
    ip = _normalize(ip)
    return (
        not ip.is_global
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_url(
    url: httpx.URL | str,
    *,
    resolver: Resolver = default_resolver,
    deny_hosts: Iterable[str] = DEFAULT_DENY_HOSTS,
    deny_suffixes: Sequence[str] = DEFAULT_DENY_SUFFIXES,
) -> None:
    """Raise :class:`SsrfError` unless ``url`` is a safe outbound-fetch target (sync).

    Checks, in order: scheme allow-list → host presence → host deny-list/suffix →
    resolved-IP public-routability (literal IPs are checked directly, hostnames are resolved
    via ``resolver`` and *every* resolved address must pass). The ``deny_hosts`` /
    ``deny_suffixes`` seams leave room for a future P6 trusted-domain allow-list without
    changing callers.

    This runs DNS on the calling thread — use it in synchronous contexts or with a fast
    injected resolver in tests. Async callers (the transport) MUST use :func:`validate_url_async`
    so a blocking ``getaddrinfo`` never stalls the event loop.
    """
    host, literal = _validate_static(url, deny_hosts, deny_suffixes)
    if literal is not None:
        _validate_ips(host, [literal])
        return
    _validate_ips(host, _resolve_ips(host, resolver))


async def validate_url_async(
    url: httpx.URL | str,
    *,
    resolver: Resolver = default_resolver,
    deny_hosts: Iterable[str] = DEFAULT_DENY_HOSTS,
    deny_suffixes: Sequence[str] = DEFAULT_DENY_SUFFIXES,
    resolution_timeout: float = RESOLUTION_TIMEOUT_SECONDS,
) -> None:
    """Async counterpart of :func:`validate_url`: identical checks, event-loop-safe DNS.

    The static checks (scheme / host / deny-list) and literal-IP validation are cheap and run
    inline; only the blocking hostname resolution is offloaded to a worker thread and bounded by
    ``resolution_timeout`` so a slow or hostile DNS server cannot stall the event loop shared by
    all concurrent request streams.
    """
    host, literal = _validate_static(url, deny_hosts, deny_suffixes)
    if literal is not None:
        _validate_ips(host, [literal])
        return
    _validate_ips(host, await _resolve_ips_async(host, resolver, resolution_timeout))


def _validate_static(
    url: httpx.URL | str,
    deny_hosts: Iterable[str],
    deny_suffixes: Sequence[str],
) -> tuple[str, IPAddress | None]:
    """Run the DNS-free checks (scheme, host presence, deny-list) shared by both entry points.

    Returns ``(host, literal_ip)`` where ``literal_ip`` is set when the host is an IP literal
    (already parsed, so callers skip DNS) and ``None`` when a hostname still needs resolving.
    """
    parsed = httpx.URL(url) if isinstance(url, str) else url

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SsrfError(f"scheme {parsed.scheme!r} is not allowed (http/https only)")

    host = parsed.host
    if not host:
        raise SsrfError("URL has no host")

    host_lower = host.lower()
    denied = {h.lower() for h in deny_hosts}
    if host_lower in denied or any(host_lower.endswith(s) for s in deny_suffixes):
        raise SsrfError(f"host {host!r} is on the deny-list")

    try:
        return host, ipaddress.ip_address(host)
    except ValueError:
        return host, None  # not a literal IP → caller resolves it


def _validate_ips(host: str, ips: Sequence[IPAddress]) -> None:
    """Raise :class:`SsrfError` if *any* of ``ips`` is not publicly routable."""
    for ip in ips:
        if _is_blocked_ip(ip):
            raise SsrfError(f"host {host!r} resolves to a non-public address")


def _resolve_ips(host: str, resolver: Resolver) -> list[IPAddress]:
    """DNS-resolve ``host`` (called only for non-literal hostnames)."""
    try:
        ips = list(resolver(host))
    except OSError as exc:
        raise SsrfError(f"could not resolve host {host!r}") from exc
    if not ips:
        raise SsrfError(f"host {host!r} did not resolve to any address")
    return ips


async def _resolve_ips_async(host: str, resolver: Resolver, timeout: float) -> list[IPAddress]:
    """Resolve ``host`` off the event loop under ``timeout`` seconds.

    The blocking resolver runs in a worker thread via ``anyio.to_thread.run_sync``; the wait is
    bounded by ``anyio.fail_after`` so the event loop is freed and the caller gets a deterministic
    :class:`SsrfError` instead of hanging on a hostile DNS server. ``abandon_on_cancel=True`` lets
    the timeout fire immediately and release the loop — the abandoned worker thread finishes (or
    hits the OS resolver timeout) on its own without holding anything up.
    """
    try:
        with anyio.fail_after(timeout):
            return await anyio.to_thread.run_sync(
                _resolve_ips, host, resolver, abandon_on_cancel=True
            )
    except TimeoutError as exc:
        raise SsrfError(f"resolving host {host!r} timed out") from exc


class GuardedTransport(httpx.AsyncBaseTransport):
    """An :class:`httpx.AsyncBaseTransport` that validates every request before delegating.

    Because httpx re-invokes the transport for each redirect hop, wrapping the transport means
    the scheme + host + resolved-IP checks run on **every hop automatically** — a redirect into
    a private IP is rejected even when hop 1 was a public host (design §7.2 "re-validated per
    hop"). On rejection it raises :class:`SsrfError`, which propagates out of the ``client``
    call for the caller to fail soft on.
    """

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        *,
        resolver: Resolver = default_resolver,
        deny_hosts: Iterable[str] = DEFAULT_DENY_HOSTS,
        deny_suffixes: Sequence[str] = DEFAULT_DENY_SUFFIXES,
        resolution_timeout: float = RESOLUTION_TIMEOUT_SECONDS,
    ) -> None:
        self._inner = inner
        self._resolver = resolver
        self._deny_hosts = frozenset(h.lower() for h in deny_hosts)
        self._deny_suffixes = tuple(deny_suffixes)
        self._resolution_timeout = resolution_timeout

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await validate_url_async(
            request.url,
            resolver=self._resolver,
            deny_hosts=self._deny_hosts,
            deny_suffixes=self._deny_suffixes,
            resolution_timeout=self._resolution_timeout,
        )
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def build_guarded_client(
    *,
    inner_transport: httpx.AsyncBaseTransport | None = None,
    resolver: Resolver = default_resolver,
    deny_hosts: Iterable[str] = DEFAULT_DENY_HOSTS,
    deny_suffixes: Sequence[str] = DEFAULT_DENY_SUFFIXES,
    max_redirects: int = MAX_REDIRECTS,
    resolution_timeout: float = RESOLUTION_TIMEOUT_SECONDS,
    timeout: httpx.Timeout | float | None = None,
) -> httpx.AsyncClient:
    """Build an :class:`httpx.AsyncClient` whose every request passes the SSRF guard.

    The returned client follows redirects (each hop re-validated by :class:`GuardedTransport`)
    up to ``max_redirects`` and applies bounded connect/read timeouts. Pass ``inner_transport``
    (e.g. an :class:`httpx.MockTransport`) + a ``resolver`` in tests to serve canned responses
    with scripted DNS; production uses the real :class:`httpx.AsyncHTTPTransport` and stdlib
    resolver by default. This is the single client factory crawlers/tools use — never a raw
    ``httpx.AsyncClient(follow_redirects=True)``.
    """
    transport = GuardedTransport(
        inner_transport or httpx.AsyncHTTPTransport(),
        resolver=resolver,
        deny_hosts=deny_hosts,
        deny_suffixes=deny_suffixes,
        resolution_timeout=resolution_timeout,
    )
    return httpx.AsyncClient(
        transport=transport,
        follow_redirects=True,
        max_redirects=max_redirects,
        timeout=timeout
        if timeout is not None
        else httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
    )


async def read_capped(
    response: httpx.Response, *, max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
) -> bytes:
    """Stream ``response``'s body, aborting once ``max_bytes`` is exceeded.

    Enforced while streaming — a lying ``Content-Length`` cannot make us buffer more than the
    cap, and an unbounded/chunked body is cut off mid-download (design §7.2 "size caps …
    not just via Content-Length"). ``response`` must have been opened with ``client.stream``.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        remaining = max_bytes - total
        if len(chunk) >= remaining:
            chunks.append(chunk[:remaining])  # trim the final chunk to the budget, then stop
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)
