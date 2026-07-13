---
name: concurrent-db-workers-fakes
description: A single scripted FakeSession/FakeDBProvider breaks when two graph workers read the DB concurrently in one turn; give each its own fresh session
metadata:
  type: feedback
---

When a LangGraph turn fans out to **two DB-reading workers concurrently** (e.g. RAG +
MARKET_INTEL both call `hybrid_search`), the shared `tests.fakes.FakeDBProvider` — which
yields the *same* scripted `FakeSession` on every `db.session()` call — fails: the first
worker consumes the script and the second hits "unexpected extra execute()".

**Why:** in production each `async with db.session()` acquires an **independent** pooled
session; a single-script fake can't model two concurrent consumers, and their execute order
is nondeterministic under `ainvoke`.

**How to apply:** use `tests.fakes.FreshSessionDBProvider(factory)` — it yields a **fresh**
scripted session per `session()` call. Script each session with the **superset** sequence in
the shared relative order (e.g. `[id-scalars, chunk-rows, title-rows, role_profiles-scalars]`);
a worker that issues fewer reads simply leaves the trailing results unused. That makes the two
workers independent and order-insensitive. See `market_and_rag_session()`.

Related gotcha: `import app.agents.graph as m` binds `m` to the **compiled `graph` object**
(the `app.agents` package re-exports it under that name), not the module — use
`importlib.import_module("app.agents.graph")` to reach the module's attributes in a test.
