---
name: feedback-langgraph-async-nodes
description: A LangGraph async node forces the whole invocation onto the async API (ainvoke/astream); sync invoke/stream raises "No synchronous function provided"
metadata:
  type: feedback
---

If any node in a compiled LangGraph is an `async def` (or async-callable, e.g. an
`async def __call__` class instance), that path can only be driven via the async runtime
API — `compiled.ainvoke(...)` / `compiled.astream(...)`. Calling the sync
`compiled.invoke(...)` / `compiled.stream(...)` on a path that reaches the async node
raises `TypeError: No synchronous function provided to "<node>"`.

**Why:** LangGraph builds a Runnable per node; an async-only node has no `.func` for the
sync executor. The P4 graph mixes sync stub nodes (guardrails/workers/responder) with the
real async `Planner` node, so the production entrypoint (`run_graph`) already uses
`await graph.ainvoke(...)`.

**How to apply:** when a node does real I/O (LLM/DB), make it `async` and write its
integration tests with `async for ... in compiled.astream(...)` /
`await compiled.ainvoke(...)`, not the sync variants — even if sibling stub nodes are sync.
