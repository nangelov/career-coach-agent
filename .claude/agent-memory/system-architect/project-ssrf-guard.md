---
name: project-ssrf-guard
description: Blessed SEC-01 SSRF guard — app/net/ package (not guardrails/), GuardedTransport per-hop revalidation seam, crawler is the only in-scope fetcher, residual rebind TOCTOU accepted as cheap-to-harden.
metadata:
  type: project
---

SEC-01-ssrf-guard APPROVED rev 1 (part of the [SEC] block, S1 — must land before P6). See
[[project-security-privacy-posture]].

**Blessed placement:** the SSRF guard lives in a new `app/net/` package (`net/ssrf_guard.py`), NOT
`guardrails/`. Rationale accepted: `guardrails/` is input/output *content* safety (jailbreak/PII); SSRF is a
network-egress concern (different threat model, SoC). The task brief explicitly left the location to the
engineer, so this is design-blessed.
- **Why:** keeps §8's `guardrails/` semantics clean.
- **How to apply:** future outbound-egress utilities belong in `net/`; content-safety in `guardrails/`. §8
  module tree still needs `net/` added (logged cheap follow-up — do not re-litigate the placement).

**Blessed seam:** `build_guarded_client()` factory + `GuardedTransport` (an httpx `AsyncBaseTransport` wrapper)
+ `validate_url` with injectable `Resolver`. Wrapping the transport means httpx re-invokes it per redirect hop,
so scheme+host+resolved-IP checks run on every hop automatically (§7.2 "re-validated per hop"). `read_capped`
streams and aborts on byte cap (never trusts Content-Length).
- **How to apply:** any new crawler/tool fetching an externally-supplied URL MUST use `build_guarded_client`,
  never a raw `httpx.AsyncClient(follow_redirects=True)`.

**Scope ruling:** only *attacker-influenceable* URLs are in scope. Confirmed OUT of scope (fixed configured
endpoints via SDKs): `internet_search` → `SEARXNG_URL` (query is a param, not host), OIDC discovery/token, HF
inference/LLM. The web-searcher crawler is the ONLY externally-supplied-URL fetcher today.

**Accepted residual risk:** the guard re-resolves in `GuardedTransport` then httpx resolves+connects again → a
DNS-rebind/TOCTOU window remains (not socket-pinned; pinning breaks TLS SNI/cert). Accepted at the design gate
because the fix seam is `GuardedTransport` itself — pinning/peer-address validation drops in later with no
caller changes (cheap to unwind). Robustness sufficiency is the code-reviewer's lane, not the architect's.
