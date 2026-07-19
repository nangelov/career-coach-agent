# Task P10-05-rate-limits-per-ip-tool — per-IP and per-tool rate limits + abuse handling

- **Phase:** P10   **Status:** ENG   **Tags:** (B)

## Scope
`app/services/rate_limiting.py` (P3-04) already enforces **per-session** and **per-user** limits
(`RateLimitAction.MESSAGE` / `.UPLOAD`) via `RateLimitService` + `RedisRateLimiter`. Design §7 /
§7.5 also calls for **per-IP** and **per-tool** limits:

> "Per-session, per-user, **per-IP**, and per-tool rate limits in Redis (§7.5)."

1. **Per-IP.** Add an IP-keyed limiter layer that runs *alongside* (not instead of) the existing
   session/user limits — so a script farming guest sessions (each with its own `session_id`) is
   still capped by source IP. Read the client IP from `X-Forwarded-For` **with a trusted-proxy
   configuration** (design §7.5 explicitly flags this: HF Spaces sits behind a proxy, and reading
   the header without a trusted-proxy allowlist makes the limit attacker-spoofable). **Note:**
   plan.md's **S9** (per-IP *guest-session-creation* limit + Altcha proof-of-work + global budget
   breaker) is explicitly a **P12 go-live gate**, not this task — do not build Altcha/PoW here.
   This task's per-IP limit is a general defense-in-depth layer on top of existing
   message/upload actions, not the S9 bot-protection mechanism. Document that distinction in
   `engineer.md` so the boundary with the future P12 work is clear.
2. **Per-tool.** Add a limit on how many times a given tool (web/internet search, market-intel
   crawl trigger, dashboard write-tool, etc.) can be invoked per turn and/or per session/user
   window — this bounds a single conversation from triggering unbounded external calls (cost +
   abuse control), independent of the message-count limit.
3. **Abuse handling.** Ensure a limit hit produces a clear, non-leaky response (existing
   `RateLimitExceeded` → 429 pattern) for the new dimensions too, and that hitting a per-tool
   limit degrades gracefully (the agent turn still completes with an explanation, it doesn't crash
   the graph).

## Acceptance criteria
- [ ] New `RateLimitAction`(s) or an equivalent mechanism cover per-tool invocation limits, wired
      into the tool-calling loop (chat graph) so a single session/turn can't invoke a tool
      unboundedly.
- [ ] A per-IP limiter layer exists, reads the client IP safely (trusted-proxy config, not naive
      header trust), and is exercised by tests with both a trusted and an untrusted proxy chain.
- [ ] Hitting a new limit surfaces a clear error/response without crashing the request; existing
      per-session/per-user limits are unaffected (regression tests pass).
- [ ] `ruff`, `ruff format --check`, `mypy`, `pytest` all green.

## Design references
- dev-board/app-design-and-features.md §7 (rate-limit bullet), §7.5 (abuse & cost-exhaustion —
  read the whole section for context, but S9's Altcha/global-breaker/bot-check items are P12,
  out of scope here)
- dev-board/plan.md — Security & privacy sequencing table, rows **S9** (P12, out of scope) vs. the
  P10 tasks.md bullet this task implements (general per-IP/per-tool limits)
- `backend/app/services/rate_limiting.py`, `backend/app/repositories/redis.py`

## Constraints / non-goals
- No Altcha / proof-of-work / global daily budget breaker — that's S9, P12.
- Reuse the existing `RateLimiter` port / `RedisRateLimiter` adapter pattern; don't fork a second
  rate-limiting mechanism.
