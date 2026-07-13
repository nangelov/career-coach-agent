---
name: project-ssrf-guard
description: SSRF guard for outbound crawler/tool fetches — where it lives and the guarded-transport pattern
metadata:
  type: project
---

Every outbound fetch of an **externally-supplied URL** (crawled pages, doc-extracted URLs, LLM
tool-call args) must route through `app/net/ssrf_guard.py` (design §7.2). Fixed configured URLs
(SearXNG `SEARXNG_URL`, OIDC metadata, HF inference via SDK) are OUT of scope — not attacker-controlled.

**Why:** v1's `follow_redirects=True` with no validation was the highest-severity code gap — a crawled
302 could reach co-located `redis`/`db` or `169.254.169.254`.

**How to apply:**
- Guard is `GuardedTransport(httpx.AsyncBaseTransport)` wrapping an inner transport + `build_guarded_client()`
  factory. Because httpx re-invokes the transport per redirect hop, wrapping the transport auto-revalidates
  every hop (scheme + host deny-list + resolved-IP public-routability). Cap hops via client `max_redirects`.
- IP check uses `ipaddress.is_global` plus explicit private/loopback/link-local/etc.; normalize IPv4-mapped-IPv6.
- Size cap: `read_capped(response, max_bytes=...)` streams + aborts (never trusts Content-Length).
- **Test seam:** inject `inner_transport=httpx.MockTransport(...)` + a fake `resolver` (host→IP). `tests/fakes.py`
  `fake_crawl_client` wraps its MockTransport in a guarded client with `public_resolver`, so all crawler tests
  exercise the guard. SSRF-rejection tests inject a resolver mapping a host to a private IP.
