---
name: feedback-redis-protocol-cast
description: A concretely-typed redis.asyncio.Redis does NOT structurally satisfy our strict RedisLike/SessionRedis Protocols under mypy — cast at the composition root
metadata:
  type: feedback
---

When wiring a real `redis.asyncio.Redis` into a hand-rolled structural `Protocol`
(e.g. the router's `RedisLike`, or a session store's `SessionRedis`), mypy `--strict`
**fails** the structural match: redis-py's own method signatures return
`Awaitable[Any] | Any` (and take `bytes|str|memoryview`, `int|timedelta`), which is too
loose to satisfy a Protocol whose methods return `Any` (i.e. `Coroutine[...]`).

**Why:** P1-04 sidestepped this accidentally because it assigned the result of an
*untyped* `redis.asyncio.from_url(...)  # type: ignore[no-untyped-call]` (typed `Any`,
never checked). Once you get the client from a properly-typed provider
(`ConnectionPool` + `Redis(connection_pool=...)`), mypy checks it and the mismatch
surfaces.
**How to apply:** keep the `Protocol` seam (so tests inject a fake), but `cast()` the
real client to each Protocol at the **single composition-root boundary** (e.g. inside
`build_chat_service`), with an inline comment. Do NOT put `# type: ignore` on
`ConnectionPool.from_url` in redis 6.x — it's typed there, so the ignore is flagged
unused. See [[project-dev-board-path]] and [[feedback-ci-curated-deps]] (redis is present
in CI via `celery[redis]`, so importing `redis.asyncio` at module top is fine).
