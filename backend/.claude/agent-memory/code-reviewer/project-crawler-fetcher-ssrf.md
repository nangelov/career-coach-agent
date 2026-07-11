---
name: project-crawler-fetcher-ssrf
description: Any v2 worker/tool that server-side fetches URLs derived from untrusted data (crawler, role-page extractor, job-listing fetcher) is an SSRF surface — check scheme/IP allowlist + redirect handling
metadata:
  type: project
---

When reviewing code that issues a server-side HTTP request to a URL that came from **untrusted external data** (search results, crawled links, job-listing URLs) — e.g. `app/agents/web_searcher.py::_crawl_page` (P4-05), and the later P6 role-page/job-listing extractors — treat it as an **SSRF surface**.

**Why:** v2 is self-hosted with Redis + Postgres **co-located on the same host/network** (docker-compose / HF Space), so a server-side `GET` to a private/loopback/link-local address or the cloud metadata endpoint (`169.254.169.254`) can reach internal services. `follow_redirects=True` widens it: a public page can 3xx-redirect to an internal target. The fetched *text* being inert (injection-safe) does NOT close the SSRF hole — that is a separate concern from prompt-injection.

**How to apply:**
- Check for a scheme guard (only `http`/`https`) and a **resolve-then-block** of private/loopback/link-local/metadata IP ranges *before* the request. Absent = SSRF finding.
- Check redirect handling — unbounded `follow_redirects=True` with no per-hop re-validation means the block is bypassable via redirect.
- Severity call: URLs sourced from a **search engine** (attacker must poison results) → usually **minor**, non-gating, recommend a `TODO(P10)` allowlist and carry into P10's untrusted-content hardening. URLs sourced **directly from user input** → escalate toward **major**.
- Confirm the fetch is still bounded (timeout, max bytes, capped page count) and per-URL fail-soft — those are correctness, orthogonal to SSRF.
