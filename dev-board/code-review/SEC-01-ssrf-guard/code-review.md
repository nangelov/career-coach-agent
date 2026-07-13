# Code review — SEC-01-ssrf-guard · engineer revision 2

## Verdict: APPROVED

## Revision 2 re-review
Both actionable prior findings are resolved; the residual (C2) was correctly left documented per my prior direction.

| id | severity | file:line | status | verification |
|----|----------|-----------|--------|--------------|
| C1 | major | backend/app/net/ssrf_guard.py | **RESOLVED** | Blocking DNS is now off the event loop. `_validate_static` splits out the DNS-free checks; hostname resolution runs via `_resolve_ips_async` → `anyio.to_thread.run_sync(_resolve_ips, ..., abandon_on_cancel=True)` bounded by `anyio.fail_after(resolution_timeout=5.0)`, mapping `TimeoutError`→`SsrfError` (ssrf_guard.py:267-284). `GuardedTransport.handle_async_request` now `await`s `validate_url_async` (:312-319). Literal-IP hosts still skip DNS entirely. Tests `test_async_validation_offloads_dns_to_worker_thread` (asserts resolver thread != main thread) and `test_async_validation_times_out_on_hostile_dns` (5s-sleeping resolver cut off at 0.05s) directly exercise the fix. Injected-resolver test seam preserved. |
| C2 | minor | ssrf_guard.py:33-40 (docstring) | Accepted residual (not gating) | No change, as directed. Re-resolve-and-validate-per-hop posture kept and documented; peer-address pinning remains an in-`GuardedTransport` future option with no caller change. |
| C3 | nit | ssrf_guard.py:362-380 | **RESOLVED** | `read_capped` now computes `remaining = max_bytes - total` and, when a chunk meets/exceeds the budget, appends only `chunk[:remaining]` then breaks — the final chunk is trimmed before buffering rather than buffered whole. Cap is now a tight hard limit. Cap tests still pass. |

## Notes
- Re-verified: `pytest tests/test_ssrf_guard.py tests/test_web_searcher.py -q` → **48 passed**; `ruff check app/net/ tests/test_ssrf_guard.py` and `mypy app/net/` both clean.
- `abandon_on_cancel=True` under `fail_after` is the right call: the timeout releases the event loop immediately and the abandoned worker thread drains on its own (or hits the OS resolver timeout) without holding the request path. `anyio.fail_after` raising the builtin `TimeoutError` is correctly caught.
- The async path re-uses the exact same static + IP predicates as the sync `validate_url`, so there is no risk of the two variants drifting in what they reject (`test_async_validation_matches_sync_rejection` guards this).
- All acceptance criteria remain met; the rev-1 security logic (scheme allow-list, resolved-IP checks incl. `169.254.169.254`/CGNAT/TEST-NET/IPv4-mapped-IPv6, deny-list-before-DNS, per-hop redirect re-validation, streamed size cap over a lying Content-Length) is unchanged and still correct. No functionality weakened.
