"""Unit tests for trusted-proxy-aware client IP resolution (P10-05, §7.5).

Asserts the safe read: an untrusted peer's ``X-Forwarded-For`` is ignored (unspoofable), a
trusted proxy's header is honored and the real client extracted past a chain of trusted proxies,
and the empty-allowlist default never trusts the header.
"""

from __future__ import annotations

from app.security.client_ip import UNKNOWN_CLIENT_IP, ClientIpResolver


def test_empty_allowlist_never_trusts_header() -> None:
    resolver = ClientIpResolver([])
    # No trusted proxies configured → XFF ignored, the direct peer is used.
    assert resolver.resolve(peer="203.0.113.9", forwarded_for="1.2.3.4") == "203.0.113.9"


def test_untrusted_peer_cannot_spoof_via_header() -> None:
    resolver = ClientIpResolver(["10.0.0.0/8"])
    # The peer is not a trusted proxy → the spoofed header is ignored, the peer wins.
    assert resolver.resolve(peer="203.0.113.9", forwarded_for="1.2.3.4") == "203.0.113.9"


def test_trusted_proxy_extracts_real_client_from_header() -> None:
    resolver = ClientIpResolver(["10.0.0.1"])
    # Peer is the trusted proxy → the right-most non-trusted XFF entry is the real client.
    assert resolver.resolve(peer="10.0.0.1", forwarded_for="198.51.100.7") == "198.51.100.7"


def test_trusted_proxy_walks_past_chain_of_trusted_proxies() -> None:
    resolver = ClientIpResolver(["10.0.0.0/8"])
    # client → trustedA → trustedB → server: strip the trusted hops, keep the real client.
    resolved = resolver.resolve(peer="10.0.0.2", forwarded_for="198.51.100.7, 10.0.0.9, 10.0.0.3")
    assert resolved == "198.51.100.7"


def test_trusted_proxy_with_all_trusted_chain_falls_back_to_peer() -> None:
    resolver = ClientIpResolver(["10.0.0.0/8"])
    # No non-trusted entry in the chain → fall back to the (trusted) peer rather than crash.
    assert resolver.resolve(peer="10.0.0.2", forwarded_for="10.0.0.9") == "10.0.0.2"


def test_trusted_proxy_with_empty_header_uses_peer() -> None:
    resolver = ClientIpResolver(["10.0.0.1"])
    assert resolver.resolve(peer="10.0.0.1", forwarded_for=None) == "10.0.0.1"


def test_no_peer_returns_unknown_bucket() -> None:
    resolver = ClientIpResolver(["10.0.0.1"])
    assert resolver.resolve(peer=None, forwarded_for="1.2.3.4") == UNKNOWN_CLIENT_IP


def test_cidr_allowlist_matches_subnet() -> None:
    resolver = ClientIpResolver(["172.16.0.0/12"])
    assert resolver.resolve(peer="172.16.5.5", forwarded_for="8.8.8.8") == "8.8.8.8"
    # A peer just outside the subnet is untrusted → header ignored.
    assert resolver.resolve(peer="172.32.0.1", forwarded_for="8.8.8.8") == "172.32.0.1"


def test_malformed_allowlist_entry_is_dropped_not_fatal() -> None:
    # A garbage entry must not crash construction; it simply is not trusted.
    resolver = ClientIpResolver(["not-an-ip", "10.0.0.1"])
    assert resolver.resolve(peer="10.0.0.1", forwarded_for="9.9.9.9") == "9.9.9.9"
