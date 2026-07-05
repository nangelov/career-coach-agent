---
name: pattern-p1-walking-skeleton
description: Interim design patterns blessed for the P1 chat walking skeleton (prompt, DI, memory seam)
metadata:
  type: project
---

Design patterns accepted as **interim** for P1's "no multi-agent yet" walking skeleton (`POST /api/chat`,
task P1-04). All are documented in engineer.md as deferred; do not re-litigate them at P1, but hold the
follow-up owners to them:

- **Chat loop lives in a single `ChatService`** (model⇄tools loop over `LLMRouter` + `ToolRegistry`), NOT
  LangGraph. Correct — LangGraph/`agents/graph.py` is P4. Reject any premature LangGraph coupling in P1.
- **`DEFAULT_SYSTEM_PROMPT` hardcoded in `services/chat.py`** — OK for skeleton; full prompt sourcing lands
  with the multi-agent graph in P4.
- **Lazy DI in `api/chat.py`** (`build_chat_service` constructs router + `redis.asyncio` client + registry,
  cached on `app.state`) — accepted composition-root stand-in; §4/§8 shared connection pools move to P2.
- **`InMemorySessionMemory` in services/** — see [[ruling-session-memory-placement]] (Redis impl → repositories/
  in P1-05).
- **`ChatRequest.history` escape hatch** — see [[ruling-client-history-trust]].
- **SSE vocabulary** (`start`/`token`/`tool_call`/`tool_result`/`done`/`error`) is defined authoritatively in
  `schemas/chat.py`; the design left this to implementation. P1-08 (Next.js) consumes it verbatim.

**How to apply:** Use as the baseline when reviewing P1-05/06/07/08 so verdicts stay consistent — each of these
interim shortcuts has a named later owner; verify that owner actually closes it.
