---
name: check-ssrf-network-egress-tasks
description: Reviewing SEC/net outbound-fetch + SSRF-guard tasks (backend/app/net/): blocking-DNS-in-async, rebinding TOCTOU, streamed size cap, scope of externally-supplied URLs
metadata:
  type: project
---

Checklist when reviewing SSRF-guard / outbound-egress tasks (SEC-01 built `backend/app/net/ssrf_guard.py`: `validate_url`, `GuardedTransport`, `build_guarded_client`, `read_capped`).

**Why:** crawler/tool fetches of attacker-influenceable URLs are the top-severity gap (design §7.2). The guard logic tends to be correct, but the *async hygiene* around it is where real defects hide.

**How to apply — check each:**
- **Blocking DNS in the async path (the recurring catch).** `socket.getaddrinfo` / `socket.gethostbyname` is blocking. If called from an `async` transport hook / node (the crawl runs as an async LangGraph `web_search_node` in the SSE request path), it stalls the whole event loop per hop. Attacker controls the domain → controls DNS latency → event-loop DoS. Require `anyio.to_thread`/`loop.getaddrinfo` + an explicit resolution timeout. This was SEC-01 rev-1's gating (major) finding.
- **DNS-rebinding TOCTOU.** A guard that re-resolves the host *independently* of httpx's own subsequent resolve/connect does NOT close rebinding (fast-flip DNS: public to the guard, private to the connect). Task wording "validate the socket's peer address" or pin-and-connect is stronger. Acceptable as a *documented* residual for a crawler (pinning breaks SNI/cert) — note it, don't gate on it alone.
- **Streamed size cap, not header trust.** Confirm the body is capped while streaming (abort mid-download), never via `Content-Length`. Watch the off-by-one: appending a whole chunk before the size check buffers one oversized chunk (nit).
- **Per-hop redirect re-validation.** Wrapping the httpx transport gets this for free (httpx re-invokes it each hop). Confirm no lingering `follow_redirects=True` on a raw client; `max_redirects` bounds hops.
- **Scope of "externally-supplied URL".** Only attacker-influenceable URLs need the guard. Fixed configured service URLs via SDKs (SearXNG `SEARXNG_URL`, OIDC discovery/token, HF inference, Postgres/Redis) are correctly out of scope — don't demand they be routed through it.
- IP checks: verify `169.254.169.254`, RFC1918, loopback, link-local, CGNAT (`100.64/10`), TEST-NET, unspecified, and IPv4-mapped-IPv6 normalization (`::ffff:a.b.c.d`) are all rejected; literal-IP hosts validated without DNS; deny-list (`localhost`/`db`/`redis`/`backend`/`.internal`) short-circuits before DNS.
