# net — outbound network egress helpers.
#
# Houses the shared SSRF guard (design §7.2): the single, reusable outbound-fetch
# validator every crawler / tool that fetches an *externally-supplied* URL must go
# through. Kept in its own package (network-egress concern) rather than under
# ``guardrails/`` (input/output *content* safety) — different concern, different
# threat model.
from app.net.ssrf_guard import (
    DEFAULT_MAX_RESPONSE_BYTES,
    MAX_REDIRECTS,
    GuardedTransport,
    SsrfError,
    build_guarded_client,
    read_capped,
    validate_url,
)

__all__ = [
    "DEFAULT_MAX_RESPONSE_BYTES",
    "MAX_REDIRECTS",
    "GuardedTransport",
    "SsrfError",
    "build_guarded_client",
    "read_capped",
    "validate_url",
]
