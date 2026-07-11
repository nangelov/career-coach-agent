---
name: schemas-independent-of-agents
description: Keep app/schemas/ (wire DTOs) free of app/agents/ imports; the service maps internal AgentState types to wire DTOs
metadata:
  type: feedback
---

The `app/schemas/` layer (SSE/HTTP wire contracts) must not import from `app/agents/`
(internal graph types). When an SSE event needs to carry graph data (e.g. `AgentState.Citation`
on the `done` event), define a **separate wire DTO** in `schemas/` (e.g. `SourceCitation`) and
map internal → wire in the **service** layer (which legitimately imports both).

**Why:** layering runs Router → Service → Agent/Repo; `agents/state.py` already imports
`schemas/auth`, so a back-import from `schemas/chat` → `agents/state` inverts the dependency and
risks cycles. The small field duplication (a 5-field DTO) is the accepted DTO/SoC cost.

**How to apply:** when adding an SSE/response field sourced from `AgentState` (P4 graph), add a
plain schema model in `schemas/chat.py` and a `_to_<dto>()` mapper in `services/chat.py`; never
`from app.agents... import` inside `schemas/`.
