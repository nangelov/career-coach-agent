---
name: ruling-market-query-rate-limit-action
description: Market/roles queries reuse RateLimitAction.MESSAGE (guest chat budget); dedicated MARKET_QUERY is a live follow-up
metadata:
  type: project
---

`/api/roles/{role}/requirements` (P6-07) rate-limits on `RateLimitAction.MESSAGE`, sharing the
guest 10-message chat budget (§6.8). Only `MESSAGE` and `UPLOAD` actions exist.

**Why:** §5.6 says guests can query market requirements but does **not** define a separate
market-query budget — under-specified, not wrong. Engineer picked MESSAGE to avoid config/`_policy`
scope creep. Cheap to decouple later (add `RateLimitAction.MARKET_QUERY`).

**How to apply:** accept MESSAGE reuse as APPROVED-with-follow-up; do not re-bless silently and do
not escalate to a blocker unless product explicitly requires guests to browse market data without
spending chat budget. If a later task adds a market action, that's the resolution of this
follow-up, not a new deviation.
