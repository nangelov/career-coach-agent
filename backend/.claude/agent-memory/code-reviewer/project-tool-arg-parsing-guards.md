---
name: project-tool-arg-parsing-guards
description: When reviewing code that parses native tool-call JSON arguments (planner, agents, tools), check EVERY field's type is guarded — a half-guarded parse raises out of a fail-soft node and 500s the turn
metadata:
  type: project
---

Code that parses `ToolCall.function.arguments` (native tool-calling, e.g. `app/agents/planner.py::_parse_decision`) must treat the arguments as **fully untrusted** — the model (esp. the Qwen failover tier) can return schema-violating types even under forced `tool_choice`.

**Why:** these parsers sit inside fail-soft graph nodes whose explicit contract is "malformed tool call → safe default, never raises out of the node." A partially-guarded parse (checks `intent` is a str but iterates `steps` without an `isinstance(list)` check) raises `TypeError` on `steps=null/5/true`, which escapes the `except json.JSONDecodeError` / `except LLMError` and propagates out of the node → 500s the whole turn. Found in P4-03 planner rev 1 (C1, major).

**How to apply:** for each field pulled from parsed tool args, verify a type guard precedes any use that assumes the type:
- iterating a field → guard `isinstance(x, list)` first (a JSON *string* also iterates, silently producing per-character junk — same bug, non-crashing variant).
- the enclosing parse should either guard every field or wrap its body in `except Exception → return None`. Catching only `json.JSONDecodeError` is not enough.
- confirm the caller's try/except is narrow on purpose (`except LLMError`, not bare `Exception`) so `CancelledError` still propagates — which means the parse itself must not raise. See [[project-chat-llm-review-checks]].
- check tests actually cover non-list / wrong-type fields, not just missing/blank/valid.
