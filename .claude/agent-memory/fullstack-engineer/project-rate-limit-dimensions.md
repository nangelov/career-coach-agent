---
name: project-rate-limit-dimensions
description: Adding new rate-limit dimensions (per-IP, per-tool) — reuse the RateLimiter port + trusted-proxy IP read
metadata:
  type: project
---

New rate-limit dimensions reuse the existing `RateLimiter` port + `RateLimitService`
(`app/services/rate_limiting.py`) — never fork a second mechanism.

**Why:** P10-05 required per-IP + per-tool limits alongside the P3-04 per-session/user ones;
the task explicitly said reuse `RedisRateLimiter`. **How to apply:**
- Add a `RateLimitAction` enum value per dimension (namespaces the Redis counter key).
- Per-IP: `enforce_ip(ip)` raises `RateLimitExceeded(action=IP)` → mapped to 429 in
  `rate_limit_exceeded_http`. Read the client IP via a **trusted-proxy allowlist**
  (`app/security/client_ip.py` `ClientIpResolver`): trust `X-Forwarded-For` only when the
  peer is in the allowlist, else use the peer (unspoofable). Empty allowlist = safe default.
- Per-tool: must **degrade gracefully, never raise** (a hit must not crash the graph). Wire it
  into the tool loop via a structural `ToolInvocationLimiter` Protocol on `ToolRegistry`
  (in `app/tools/base.py`) with an `async allow(tool_name) -> bool`. `RateLimitService`'s
  bound adapter (`SessionToolRateLimiter`) satisfies it **structurally** → no services→tools
  import (avoids a cycle). A denied call returns a `ToolResult.error(...)` tool message.
- S9 (per-IP guest-session-creation gate + Altcha/PoW + global budget breaker) is a **separate
  P12** task — the P10 per-IP limit is general defense-in-depth, not the bot gate.
