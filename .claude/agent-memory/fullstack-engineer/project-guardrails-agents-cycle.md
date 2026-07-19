---
name: project-guardrails-agents-cycle
description: guardrails is a lower layer than agents; importing app.agents.state at module-load closes an import cycle
metadata:
  type: project
---

`app.guardrails` is a **lower layer** than `app.agents` (`app.agents.graph` imports
`app.guardrails`). Importing `app.agents.state` (for `GuardrailStage`/`SafetyVerdict`) at a
guardrails module's **top level** runs `app.agents.__init__`, which eagerly loads
`agents.graph` → `agents.responder` → back into `app.guardrails` → import cycle.

**Why:** it only bites when something enters `guardrails` *before* `agents` is fully loaded
(e.g. `app.ingestion.structuring` importing `fence_untrusted`) — otherwise ordering hides it.

**How to apply:** in `guardrails`, import `agents.state` types **lazily inside functions**
(runtime) + under `TYPE_CHECKING` (annotations), never at module top. Same rule for any lower
layer needing an `agents`-package symbol. `guardrails.untrusted_content` is a pure leaf (stdlib
only) on purpose — keep it that way.

**Same cycle bit `app.memory.store`** (P9-03): it imported `from app.agents.rag_agent import
SessionProvider` at module top → fine when `agents` loads first, but broke the moment `app.memory`
was imported first (a task importing `app.memory.learn` runs the `app.memory` package init →
store). `SessionProvider` was only an annotation, so moving it under `TYPE_CHECKING` broke the
cycle. Watch this whenever a new `app.memory` / `app.tasks` module makes `app.memory` an import
entrypoint.
