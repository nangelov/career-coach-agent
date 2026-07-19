# Engineer report — P10-05-rate-limits-per-ip-tool · Revision 1

## Summary
Added **per-IP** and **per-tool** rate-limit layers on top of the existing P3-04
per-session/per-user limits, reusing the same `RateLimiter` port / `RedisRateLimiter` adapter
(no second mechanism).

- **Per-IP** (§7.5 defense-in-depth): a request cap keyed on the *source IP*, read via a
  **trusted-proxy allowlist** so `X-Forwarded-For` is only honored behind a configured proxy
  (else the direct peer is used and the header is ignored — unspoofable). Runs *alongside* the
  message limit on `POST /api/chat`, so a script farming fresh guest `session_id`s from one IP is
  still bounded.
- **Per-tool** (§7 / §7.5): a per-caller, per-tool-name invocation cap wired into the tool-calling
  loop via a structural `ToolInvocationLimiter` seam on `ToolRegistry`. A hit **degrades
  gracefully** — the model gets a rate-limit tool message and wraps up the turn; it never raises
  or crashes the graph.
- **Abuse handling**: per-IP over-budget → clear, non-leaky `429` (`Too many requests from your
  network …`) with `Retry-After`; per-tool over-budget → graceful in-loop tool message.

**Boundary with P12/S9 (documented per task):** this per-IP layer is a *general* request cap. It
is **not** the S9 go-live gate (per-IP *guest-session-creation* limit + Altcha proof-of-work +
global daily budget breaker) — that remains a separate P12 task. No Altcha/PoW/budget-breaker
built here.

## Files changed
- `app/config.py` — new settings: `TRUSTED_PROXIES`, `IP_MAX_REQUESTS_PER_WINDOW`,
  `IP_RATE_LIMIT_WINDOW_SECONDS`, `TOOL_MAX_CALLS_PER_WINDOW`, `TOOL_RATE_LIMIT_WINDOW_SECONDS`.
- `app/services/rate_limiting.py` — `RateLimitAction.IP` / `.TOOL`; refactored `_subject`;
  `enforce_ip()` (raises), `check_tool()` (never raises), `tool_limiter()` +
  `SessionToolRateLimiter` adapter; `from_settings`/ctor thread the new limits.
- `app/security/client_ip.py` (new) — `ClientIpResolver`: trusted-proxy-aware client-IP read
  (allowlist of IPs/CIDRs; empty = safe default that never trusts XFF).
- `app/tools/base.py` — `ToolInvocationLimiter` Protocol; `ToolRegistry(invocation_limiter=…)`
  consults it before dispatch, returning a graceful rate-limit tool message on denial.
- `app/agents/dashboard_agent.py` — `make_dashboard_node(rate_limiter=…)`; builds a per-turn
  caller-bound `tool_limiter` and passes it to the loop's `ToolRegistry`.
- `app/agents/graph.py` — `rate_limiter` param threaded through `build_graph`,
  `GraphTurnStreamer`, `stream_graph` into the dashboard node.
- `app/security/dependencies.py` — `get_client_ip_resolver` / `get_client_ip` deps; `IP` branch
  in `rate_limit_exceeded_http`.
- `app/api/chat.py` — enforces `enforce_ip(client_ip)` before the message cap (authz still first).
- `app/app_state.py` — `CLIENT_IP_RESOLVER` state key.
- `app/bootstrap.py` — `build_chat_service` injects the shared `RateLimitService` into the graph.
- Tests: `tests/test_client_ip.py` (new), extended `tests/test_rate_limiting.py`,
  `tests/test_tools.py`, `tests/test_authz_ratelimit_api.py`, `tests/test_dashboard_agent.py`.

## Key decisions
- **Reuse the `RateLimiter` port, not a fork** (task constraint / §7.5): IP + tool are just new
  key namespaces + policy methods on `RateLimitService`; the Redis fixed-window adapter is unchanged.
- **Trusted-proxy allowlist over naive XFF** (§7.5): peer must be in `TRUSTED_PROXIES` before the
  header is read; otherwise the peer address is used. Anti-spoof is proven by tests with both a
  trusted and an untrusted proxy chain. Empty default = XFF never trusted (safe on a bare bind).
- **Per-tool degrades, never raises** (§7.5 abuse handling): a structural `ToolInvocationLimiter`
  on `ToolRegistry` keeps the registry agnostic of rate-limit config; the services-layer adapter
  satisfies it *structurally*, so services never import the tools layer (no cycle). Denied → a
  `ToolResult.error` tool message the model wraps up on. Chose per-session/user *window* keying
  (Redis, cross-worker) over per-turn in-process, consistent with the rest of the limiter.
- **Chose the `ToolRegistry.execute` chokepoint** as the single per-tool enforcement point — any
  current/future model-driven tool loop (today: the dashboard worker) gets the cap uniformly (DRY).

## How to verify
- `cd backend && .venv/bin/ruff check app/ tests/ && .venv/bin/ruff format --check app/ tests/`
- `.venv/bin/mypy app/`  (the CI gate — `Makefile` runs `mypy app/ migrations/`)
- `.venv/bin/python -m pytest -q`
- Behaviour: `test_per_ip_limit_keys_on_client_behind_trusted_proxy` (trusted chain →
  per-client-IP budget) and `test_per_ip_limit_ignores_spoofed_header_from_untrusted_peer`
  (untrusted peer → header ignored, spoofing can't evade); `test_client_ip.py` (resolver units);
  `test_per_tool_limit_bounds_repeated_tool_calls_without_crashing` (loop caps + completes).

## Tests (final step — mandatory)
- `ruff check` → All checks passed. `ruff format --check` → 259 files already formatted.
- `mypy app/` → Success: no issues found in 150 source files.
- `pytest -q` (full suite) → **924 passed, 83 skipped** (skips are pre-existing live-DB/ML gates).
- No failures; nothing fixed-to-pass. (Note: `mypy tests/` surfaces one *pre-existing* union-attr
  warning in `test_dashboard_agent.py:282` on `dashboard_result.content.lower()` — code I did not
  touch; tests are not in the mypy gate, which is `app/ migrations/`.)

## Self-check
- [x] Meets acceptance criteria: per-tool action wired into the tool loop (bounded, graceful);
      per-IP layer with trusted-proxy read, tested with trusted + untrusted chains; new limits
      surface clearly without crashing; existing per-session/user limits unaffected (regression
      tests green).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (API reads IP + calls
      `RateLimitService`; per-tool policy lives in the service; registry stays config-agnostic).
- [x] Tests/lints pass (pasted above).
