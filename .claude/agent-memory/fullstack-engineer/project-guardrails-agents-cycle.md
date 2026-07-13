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
