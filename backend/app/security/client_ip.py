"""Trusted-proxy-aware client IP resolution for per-IP rate limiting (P10-05, §7.5).

On HF Spaces the app sits **behind a reverse proxy**, so the immediate TCP peer is the proxy,
not the real client — the client address is carried in the ``X-Forwarded-For`` (XFF) header.
But XFF is client-supplied and trivially spoofable: reading it naively lets an attacker forge a
fresh source IP per request and evade the per-IP limit entirely (design §7.5 explicitly flags
this). This module resolves the client IP **safely** via a *trusted-proxy allowlist*:

* If the immediate peer is **not** a configured trusted proxy, the XFF header is **ignored**
  and the peer address is used — an untrusted direct client cannot spoof its source IP.
* If the peer **is** a trusted proxy, the header is parsed and the right-most address that is
  **not** itself a trusted proxy is taken as the real client (walking left past any chain of
  trusted proxies). If the whole chain is trusted / empty, the peer is used as a fallback.

The allowlist accepts single IPs (``10.0.0.1``) and CIDR networks (``10.0.0.0/8``), so a
deployment can trust the platform proxy subnet. An **empty** allowlist is the safe default:
XFF is never trusted, the peer is always used.
"""

from __future__ import annotations

from collections.abc import Sequence
from ipaddress import ip_address, ip_network

from app.config import Settings, settings

#: Returned when no peer address is available at all (exotic transports / test clients with no
#: ``request.client``) — a single shared bucket so the limiter always has a key to count against.
UNKNOWN_CLIENT_IP = "unknown"


class ClientIpResolver:
    """Resolve the trusted client IP from the peer address + ``X-Forwarded-For`` (§7.5).

    Built once from the configured trusted-proxy allowlist. Stateless and cheap; share one
    instance app-wide (cached on ``app.state``).
    """

    def __init__(self, trusted_proxies: Sequence[str] = ()) -> None:
        # Parse each entry once as a network (a bare IP becomes a /32 or /128). ``strict=False``
        # tolerates a host address written with a prefix. Unparseable entries are dropped (a
        # misconfigured allowlist must not crash startup — it degrades to "trust fewer proxies").
        self._networks = []
        for entry in trusted_proxies:
            try:
                self._networks.append(ip_network(entry, strict=False))
            except ValueError:
                continue

    @classmethod
    def from_settings(cls, config: Settings = settings) -> ClientIpResolver:
        """Build from ``TRUSTED_PROXIES`` (empty → XFF never trusted; peer always used)."""
        return cls(config.TRUSTED_PROXIES)

    def _is_trusted(self, ip: str) -> bool:
        try:
            addr = ip_address(ip)
        except ValueError:
            return False
        return any(addr in network for network in self._networks)

    def resolve(self, *, peer: str | None, forwarded_for: str | None) -> str:
        """Return the client IP to rate-limit on, honoring the trusted-proxy configuration.

        Args:
            peer: The immediate TCP peer address (``request.client.host``), or ``None``.
            forwarded_for: The raw ``X-Forwarded-For`` header value, or ``None``.
        """
        if peer is None:
            return UNKNOWN_CLIENT_IP
        # Untrusted / unconfigured peer: never trust the header (it is spoofable) — key on the
        # real connecting address.
        if not self._networks or not self._is_trusted(peer):
            return peer
        # Trusted proxy: the real client is the right-most XFF entry that is not itself a trusted
        # proxy (walk left past a chain of trusted proxies). All-trusted / empty → fall back to
        # the peer so we always return a concrete address.
        chain = [hop.strip() for hop in (forwarded_for or "").split(",") if hop.strip()]
        for hop in reversed(chain):
            if not self._is_trusted(hop):
                return hop
        return peer
