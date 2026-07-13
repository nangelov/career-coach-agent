# Engineer report — SEC-01-ssrf-guard · Revision 2

## Revision 2 summary
Addressed code-review blocker **C1** (event-loop-blocking DNS) and the **C3** nit. DNS resolution
is now offloaded from the event loop under an explicit timeout on the async transport path; the
oversized-chunk buffering was tightened. Architecture review was already APPROVED — no changes
needed there. See `Response to review` at the bottom.

- `pytest tests/test_ssrf_guard.py tests/test_web_searcher.py -q` → **48 passed**.
- Full suite `pytest -q` → **445 passed, 49 skipped**. ruff + mypy clean.

---

# Engineer report — SEC-01-ssrf-guard · Revision 1

## Summary
Built a single, reusable outbound-fetch SSRF guard (`app/net/ssrf_guard.py`) and routed the
web-searcher crawler through it, closing the highest-severity code gap called out in design §7.2
(v1's `follow_redirects=True` with zero validation). The guard enforces scheme allow-list,
resolved-IP public-routability, per-hop-re-validated bounded redirects, a host deny-list, and a
streamed response-size cap. The crawler is the **only** externally-supplied-URL fetcher in the
backend — SearXNG (`SEARXNG_URL`), OIDC discovery/token, and HF inference all use *fixed configured*
URLs via their SDKs, so they are out of scope (not attacker-influenceable).

## Files changed
- `app/net/__init__.py` — new package; re-exports the guard's public surface.
- `app/net/ssrf_guard.py` — new module: `SsrfError`, `validate_url`, `GuardedTransport`,
  `build_guarded_client`, `read_capped`, `default_resolver`, deny-list constants.
- `app/agents/web_searcher.py` — crawl now builds an SSRF-guarded client (`build_guarded_client`)
  when none is injected; `_crawl_page` drops the raw `follow_redirects=True` (the guarded client
  follows+re-validates hops) and uses `read_capped` for the streamed size cap; docstrings updated.
- `tests/fakes.py` — `fake_crawl_client` now wraps its `MockTransport` in a guarded client with a
  `public_resolver`, so all existing crawler tests exercise the guard path; added `public_resolver`.
- `tests/test_ssrf_guard.py` — new unit suite (see acceptance mapping below).

## Key decisions
- **Guarded transport, not a bespoke fetch loop** (design §7.2 "httpx transport hook"): wrapping the
  inner transport means httpx re-invokes it for *every* redirect hop, so scheme+host+resolved-IP
  checks run per hop automatically. Redirect count is bounded via the client's `max_redirects`.
- **Location for the module → `app/net/`** (not `app/guardrails/`): guardrails is input/output
  *content* safety (jailbreak/PII); SSRF is a network-egress concern — different threat model, SoC.
- **`ipaddress.is_global` + explicit predicates**: rejects private/loopback/link-local (incl.
  `169.254.169.254`), multicast, reserved, CGNAT, TEST-NET; IPv4-mapped-IPv6 is normalized so a
  private v4 can't slip through as `::ffff:a.b.c.d`. Literal-IP hosts are validated without DNS.
- **DNS-rebind posture**: validate the resolved IP on every hop (the design-sanctioned transport-hook
  option). Not socket-pinning — that would require rewriting the request to the IP and breaking TLS
  SNI/cert validation, a worse trade for a crawler. Documented in the module docstring.
- **Deny-list seam for P6**: `deny_hosts`/`deny_suffixes` are injectable so a future trusted-domain
  allow-list drops in without touching callers — no P6 allow-list logic built now (YAGNI).
- **Test seam**: `resolver` (host→IP) and `inner_transport` are both injectable, so private-IP /
  rebind / redirect rejection is tested with zero real network or DNS.

## How to verify
- `cd backend && .venv/bin/python -m pytest tests/test_ssrf_guard.py tests/test_web_searcher.py -q`
- `.venv/bin/ruff check app/net/ tests/test_ssrf_guard.py app/agents/web_searcher.py tests/fakes.py`
- `.venv/bin/mypy app/net/ app/agents/web_searcher.py`

## Tests (final step — mandatory)
- `pytest tests/test_ssrf_guard.py tests/test_web_searcher.py -q` → **44 passed**.
- Full suite `pytest -q` → **441 passed, 49 skipped** (skips are pre-existing infra-gated
  Postgres/network integration tests, unrelated to this change).
- `ruff check` (changed files) → **All checks passed**; `mypy app/net/ app/agents/web_searcher.py`
  → **Success: no issues found**.
- No failures; nothing weakened or deleted.

Acceptance-criteria → test mapping (all in `tests/test_ssrf_guard.py`):
- non-http(s) scheme rejection → `test_rejects_non_http_schemes`.
- private/loopback/link-local incl. `169.254.169.254` (mock DNS) → `test_rejects_host_resolving_to_non_public_ip`,
  `test_rejects_literal_private_ip_without_dns`.
- redirect re-validated on hop 2+ → `test_redirect_to_private_ip_is_rejected_on_second_hop`.
- max redirect count → `test_redirect_count_is_bounded`.
- streamed size cap (lying Content-Length) → `test_read_capped_aborts_oversized_body`.
- happy-path public fetch → `test_happy_path_public_fetch_succeeds`.
- host deny-list → `test_rejects_denied_hosts_before_dns`; guard-before-delegate →
  `test_guarded_transport_blocks_private_before_delegating`.
- `web_searcher.py` no longer calls raw `httpx` with `follow_redirects=True` unguarded → verified in
  code and exercised end-to-end via `tests/test_web_searcher.py` (now on the guarded client).

## Self-check
- [x] Meets acceptance criteria (mapping above)
- [x] No secrets committed; guard is a shared interface (`GuardedTransport`/`build_guarded_client`)
      before its use in the agent layer — Router→Service→Agent layering respected
- [x] Tests/lints pass (441 passed / 49 skipped; ruff + mypy clean)
- [x] Dependency-light: stdlib `socket`/`ipaddress` + httpx transport hook only, no new library
- [x] P6 allow-list left as a seam, not built (per non-goals); `docker-compose.yml` untouched (SEC-03)

---

## Response to review (revision 2)

### Code review
- **C1 (major) — blocking `getaddrinfo` on the event loop → resolved.** Split `validate_url` into
  shared DNS-free static checks (`_validate_static`: scheme/host/deny-list + literal-IP parse) and
  IP validation (`_validate_ips`), reused by both a sync `validate_url` (unchanged public API, for
  sync/test callers) and a new async `validate_url_async`. The async variant offloads the blocking
  resolver to a worker thread via `anyio.to_thread.run_sync(..., abandon_on_cancel=True)` bounded by
  `anyio.fail_after(RESOLUTION_TIMEOUT_SECONDS=5.0)`, mapping a timeout to `SsrfError`.
  `GuardedTransport.handle_async_request` now `await`s the async variant, so no user stream can be
  stalled by a slow/hostile DNS server for an attacker-influenced host. `resolution_timeout` is
  configurable on `GuardedTransport` and `build_guarded_client`. The injected-resolver test seam is
  preserved unchanged. New tests: `test_async_validation_offloads_dns_to_worker_thread` (asserts the
  resolver runs off the event-loop thread), `test_async_validation_times_out_on_hostile_dns`
  (a 5s-sleeping resolver is cut off at a 0.05s bound), plus async parity/literal-IP tests.
- **C2 (minor, not gating) — DNS-rebind residual gap.** No change, as the reviewer directed; the
  documented re-resolve-and-validate posture is kept. The module docstring already frames it as an
  accepted residual risk with peer-address pinning available inside `GuardedTransport` later with no
  caller changes.
- **C3 (nit) — oversized chunk buffered before the size check → resolved.** `read_capped` now
  computes `remaining = max_bytes - total` and, when a chunk would meet/exceed the budget, appends
  only `chunk[:remaining]` and breaks — the final chunk is trimmed to the budget before buffering
  rather than buffered whole then sliced. Existing cap tests still pass.

### Architecture review
- APPROVED with no required changes. The two non-blocking follow-ups (add `net/` to the §8 module
  tree; C2 rebind posture) are doc/design-owner items outside this task's code scope and left for
  the noted follow-up. `net/` remains a downward-depended leaf utility; layering unchanged.
