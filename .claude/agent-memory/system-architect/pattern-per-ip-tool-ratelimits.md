---
name: pattern-per-ip-tool-ratelimits
description: P10-05 blessed per-IP + per-tool rate-limit layers extending the P3-04 RateLimiter port
metadata:
  type: project
---

P10-05 APPROVED (rev 1): per-IP + per-tool limits added as new namespaces on the existing P3-04 `RateLimiter`/`RedisRateLimiter` (see [[project-authz-ratelimit]]), no second mechanism.

- **Per-IP** = general defense-in-depth request cap (`enforce_ip`, raises → 429), keyed on trusted client IP. `security/client_ip.py` `ClientIpResolver` reads XFF only behind a `TRUSTED_PROXIES` allowlist; empty default = XFF never trusted (safe). This is NOT S9 (Altcha/PoW/global budget breaker = P12) — keep that boundary.
- **Per-tool** = `check_tool` (never raises) + `SessionToolRateLimiter` that structurally satisfies `tools.base.ToolInvocationLimiter` Protocol, enforced at the single `ToolRegistry.execute` chokepoint. Denial → graceful `ToolResult.error` tool message, never crashes the graph.

**Why:** §7.5 requires per-IP/per-tool alongside per-session/user; §7.5 abuse handling requires graceful degradation.
**How to apply:** services must NOT import the tools layer — per-tool policy reaches the registry via the structural port (service→tools inversion avoided). Agents type `RateLimitService` under TYPE_CHECKING and receive the limiter injected. Open follow-up: per-tool limiter is wired only into the dashboard worker; future model-driven tool loops (P6 crawl trigger, web search) must inject a `rate_limiter` into their `ToolRegistry` to inherit the cap.
