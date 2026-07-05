# Memory index

- [Session memory placement ruling](ruling-session-memory-placement.md) — Persistent (Redis) store impls belong in repositories/, not services/; ABC seam in services/ is OK
- [Client-supplied history trust boundary](ruling-client-history-trust.md) — Client-supplied chat history must not carry system/tool roles or forged tool_calls
- [P1 walking-skeleton scope blessings](pattern-p1-walking-skeleton.md) — Accepted interim patterns for P1 chat skeleton (hardcoded prompt, lazy DI in router module, in-memory seam)
- [message_id feedback-key ruling](ruling-message-id-feedback-key.md) — §5.5 id stamps only terminal answers; get_message is P1 plumbing, durable feedback lookup moves to Postgres in P2/P9
