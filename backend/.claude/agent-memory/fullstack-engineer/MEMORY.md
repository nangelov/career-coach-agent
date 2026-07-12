# Memory index

- [Dev-board path gotcha](project-dev-board-path.md) — dev-board/ + code-review/ + .claude/skills live at REPO ROOT, not backend/ cwd
- [CI curated deps](feedback-ci-curated-deps.md) — CI installs only light deps; never import heavy ML stack at module import time
- [CI ruff format gate](feedback-ci-ruff-format-gate.md) — backend gate runs `ruff format --check .` too; ruff version bumps drift older committed files red
- [Redis Protocol cast](feedback-redis-protocol-cast.md) — real redis.asyncio.Redis fails strict Protocol match; cast at composition root, no ignore on from_url in redis 6.x
- [aclosing vs AsyncIterator](feedback-aclosing-asynciterator.md) — contextlib.aclosing fails mypy on AsyncIterator-typed streams; use try/finally + getattr aclose for deterministic early-close
- [LangGraph async nodes](feedback-langgraph-async-nodes.md) — an async node forces ainvoke/astream; sync invoke/stream on that path raises "No synchronous function provided"
- [SQLAlchemy ColumnElement](feedback-sqlalchemy-columnelement.md) — reassigning a WHERE cond from is_()/== to or_()/and_() widens type; annotate `cond: ColumnElement[bool]` up front for strict mypy
- [schemas independent of agents](feedback-schemas-independent-of-agents.md) — schemas/ never imports agents/; define a wire DTO + map internal AgentState types in the service layer
- [Graph streaming block path](project-graph-streaming-block-path.md) — streaming responder runs SEPARATELY from pre-responder graph; short-circuits need BOTH a node/routing change AND a stream_response check
- [Phase-exit verification](phase-exit-verification.md) — Px-NN-verify: compose the real stack, fake only external edges, live-DB skip+run-once; report point-by-point
