---
name: project-always-run-node-sync-default
description: An always-run LangGraph node's unbound/default variant must be sync, or it breaks synchronous .invoke() of the import-time module graph
metadata:
  type: project
---

In `app/agents/graph.py`, nodes that **always run** on every turn (memory_recall, input
guardrail, planner, responder) must keep their **unbound/module-default** variant a **sync**
`def`, not `async def`. Conditionally-routed workers (RAG, market, dashboard) can default to
async because they only execute when the planner selects them.

**Why:** the import-time module `graph = build_graph()` (no router/db bound) is exercised by
tests that call `.invoke()` synchronously (e.g. `test_guardrail_stubs_populate_allowed_verdicts`).
LangGraph raises `TypeError: No synchronous function provided to "<node>"` if an always-run node
is async-only. The *bound* (production) variant is async — only the no-dependency default must be
sync.

**How to apply:** when replacing an always-run stub, make `make_x_node()` return a sync no-op
when its provider is `None`, and the async real closure only when bound. Run
`tests/test_agent_graph.py` after touching any always-run node.

Related: [[project-abc-port-extension-breaks-fakes]]. Also: naming a `BaseStore` subclass method
`search`/`get`/`put` clashes with `BaseStore`'s own signatures under mypy `--strict` (override
error) — give first-party methods distinct names (e.g. `search_memories`).
