# Memory index

- [Dev-board path gotcha](project-dev-board-path.md) — dev-board/ + code-review/ + .claude/skills live at REPO ROOT, not backend/ cwd
- [CI curated deps](feedback-ci-curated-deps.md) — CI installs only light deps; never import heavy ML stack at module import time
- [langmem not imported](project-langmem-not-imported.md) — langmem/trustcall declared but never imported in app/ (P9 hand-rolled); keep in curated-deps exclusion allowlist
- [CI ruff format gate](feedback-ci-ruff-format-gate.md) — backend gate runs `ruff format --check .` too; ruff version bumps drift older committed files red
- [Redis Protocol cast](feedback-redis-protocol-cast.md) — real redis.asyncio.Redis fails strict Protocol match; cast at composition root, no ignore on from_url in redis 6.x
- [aclosing vs AsyncIterator](feedback-aclosing-asynciterator.md) — contextlib.aclosing fails mypy on AsyncIterator-typed streams; use try/finally + getattr aclose for deterministic early-close
- [LangGraph async nodes](feedback-langgraph-async-nodes.md) — an async node forces ainvoke/astream; sync invoke/stream on that path raises "No synchronous function provided"
- [SQLAlchemy ColumnElement](feedback-sqlalchemy-columnelement.md) — reassigning a WHERE cond from is_()/== to or_()/and_() widens type; annotate `cond: ColumnElement[bool]` up front for strict mypy
- [schemas independent of agents](feedback-schemas-independent-of-agents.md) — schemas/ never imports agents/; define a wire DTO + map internal AgentState types in the service layer
- [Graph streaming block path](project-graph-streaming-block-path.md) — streaming responder runs SEPARATELY from pre-responder graph; short-circuits need BOTH a node/routing change AND a stream_response check
- [Phase-exit verification](phase-exit-verification.md) — Px-NN-verify: compose the real stack, fake only external edges, live-DB skip+run-once; report point-by-point
- [Concurrent DB workers in fakes](feedback-concurrent-db-workers-fakes.md) — two concurrent DB workers need FreshSessionDBProvider (fresh session per call), not a single shared FakeSession
- [Cache-first cheap key](feedback-cache-first-cheap-key.md) — cache-first read endpoints key on a cheap request-derived value, not a DB-derived canonical, so a hit skips ALL DB work
- [Market canonicalization needs taxonomy seed](project-market-canonicalization-needs-taxonomy-seed.md) — _resolve_baseline searches ALL curated docs; live mine→read tests must seed a taxonomy occupation doc or the read resolves to the summary title (202 loop)
- [Worker enum fan-in tests](feedback-worker-enum-fanin-tests.md) — adding a WorkerName/Intent member breaks tests asserting `set(WorkerName)`; dispatch the new worker, exclude citation-less workers from citation asserts
