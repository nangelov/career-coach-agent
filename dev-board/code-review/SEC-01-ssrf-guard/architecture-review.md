# Architecture review — SEC-01-ssrf-guard · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | SSRF guard exists (§7.2 "SSRF guard (crawler)", §10 Risk row, [SEC] S1) | Single reusable guard: http(s) allow-list, resolved-IP public-routability, per-hop-revalidated bounded redirects, host deny-list, timeouts + streamed size cap | `app/net/ssrf_guard.py` implements all five; `web_searcher._crawl_page` no longer passes `follow_redirects=True` raw — routes through `build_guarded_client` + `read_capped` | None |
| A2 | Module placement (§8 backend tree) | §8 lists `guardrails/` but the task explicitly left the location to the engineer (`net/` or `guardrails/`) | Placed in new `app/net/` with a documented SoC rationale (egress ≠ content safety) | Cheap follow-up: add `net/` to the §8 module tree so the doc matches reality. Not blocking — task-sanctioned choice. |
| A3 | Layering (Router→Service→Agent/Repo) | Shared egress util below the agent that consumes it; interface-before-implementation | `net/` is a leaf utility package; agent (`web_searcher`) depends on it, not vice-versa; `GuardedTransport`/`build_guarded_client`/`validate_url`/`Resolver` are real seams with injectable resolver + inner transport | None |
| A4 | Scope of guarded fetches (§7.2 "every outbound fetch in the crawler"; task: only attacker-influenceable URLs) | Crawler routed; fixed configured endpoints out of scope | Verified: `internet_search` hits fixed `SEARXNG_URL` (query is a param, not the host), OIDC discovery/token and LLM/HF inference use fixed configured URLs via SDKs — correctly excluded. Crawler is the only externally-supplied-URL fetcher. | None |
| A5 | Locked posture: dependency-light (§7.2 / task non-goals; budget §11) | stdlib `socket`/`ipaddress` + httpx transport hook, no new library | No new dependency; free/OSS/self-hosted preserved | None |
| A6 | P6 allow-list seam only (task non-goal — YAGNI) | Leave extensible deny/allow seam, do not build P6 logic | `deny_hosts`/`deny_suffixes` injectable; no P6 trusted-domain logic built | None |
| A7 | Phase fit ([SEC] S1 must land before P6) | SEC-block work, foundation for market-intel crawler | Lands in the SEC block ahead of P6; does not prematurely couple to P6 | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — new `net/` leaf package (task-sanctioned; §8 doc update is a follow-up), agent depends downward
- [x] Honors locked decisions — no new datastore/dependency; dependency-light; budget posture intact
- [x] Interfaces-before-implementations — `GuardedTransport`, `build_guarded_client`, `validate_url`, injectable `Resolver`/`inner_transport` are genuine swap seams
- [x] Budget posture respected (free/OSS/self-hosted)

## Notes
- **Design risk (defer to code-reviewer, tracked here as a follow-up):** the guard validates the target by an
  independent re-resolution in `GuardedTransport`, then delegates to httpx's inner transport which resolves +
  connects again. This leaves a residual DNS-rebind / TOCTOU window (rebinding DNS could return a public IP to
  the guard's `getaddrinfo` and a private IP on httpx's real connect). The task's two robust options were
  "resolve once and connect to the resolved IP" or "validate the socket's peer address"; this is a third
  (re-resolve-and-validate). The engineer documented the trade-off honestly (socket-pinning breaks TLS
  SNI/cert validation for a crawler). Architecturally acceptable because the hardening seam is exactly the
  right place — pinning or peer-address validation can be added inside `GuardedTransport` later with **no caller
  changes** — so it is cheap to unwind. Robustness sufficiency is the code-reviewer's call; flagged, not gated.
- Follow-up (cheap, non-blocking): add `net/` to the §8 backend module tree in
  `dev-board/app-design-and-features.md` so the structure doc reflects the sanctioned new package.
