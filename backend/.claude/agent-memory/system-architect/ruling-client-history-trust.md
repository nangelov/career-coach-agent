---
name: ruling-client-history-trust
description: Client-supplied chat history must not be able to inject system/tool roles or forge tool results
metadata:
  type: project
---

`ChatRequest.history` (the optional client-supplied prior-turns escape hatch on `POST /api/chat`) accepts a
full `list[ChatMessage]` including `role="system"` / `role="tool"` with fabricated `tool_calls`. This lets a
client inject a system prompt or forge tool results, bypassing server-owned conversation state (§4 data
ownership / trust boundary).

**Why:** Blessed for the P1 walking skeleton only — endpoint is not yet auth-gated (auth is P3) and server-side
Redis memory is P1-05. Once server-side session memory is canonical, accepting arbitrary client roles is a
data-ownership violation.

**How to apply:** When P1-05 makes Redis session memory canonical (or when auth lands in P3), require the
accepted client `history` to be constrained to `user`/`assistant` content — reject client-supplied `system`
and `tool` roles and any client-supplied `tool_calls`. The injection/security angle is the code-reviewer's
gate; the data-ownership dimension is ours.

**Status (P1-05, 2026-07-04):** Redis session memory is now canonical, but `stream_turn` still lets a
client-supplied `history` *fully override* it (`prior = list(history) if history is not None else load()`),
and the endpoint is still not auth-gated. Deferred to **P3** (auth trust boundary) by the engineer and
accepted by me as APPROVED-with-follow-up — the fix is cheap (a schema validator + prefer server memory) and
the memory-backend swap did not worsen it. This is now a **live, must-not-drop** requirement for P3, logged in
`code-review/P1-05-session-memory/architecture-review.md` (N1). Do not re-bless silently past P3.
