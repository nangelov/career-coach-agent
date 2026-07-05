# Memory index

- [Dev-board path gotcha](project-dev-board-path.md) — dev-board/ + code-review/ + .claude/skills live at REPO ROOT, not backend/ cwd
- [CI curated deps](feedback-ci-curated-deps.md) — CI installs only light deps; never import heavy ML stack at module import time
- [Redis Protocol cast](feedback-redis-protocol-cast.md) — real redis.asyncio.Redis fails strict Protocol match; cast at composition root, no ignore on from_url in redis 6.x
- [aclosing vs AsyncIterator](feedback-aclosing-asynciterator.md) — contextlib.aclosing fails mypy on AsyncIterator-typed streams; use try/finally + getattr aclose for deterministic early-close
