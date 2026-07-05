# Task P1-05-session-memory — Redis-backed per-session memory
- **Phase:** P1   **Status:** ENG   **Tags:** (B)

## Scope
Replace the interim `InMemorySessionMemory` (process-local, built in P1-04 as a deliberately narrow,
swappable seam — see `dev-board/code-review/P1-04-chat-endpoint/engineer.md`, `app/services/session_memory.py`)
with a **Redis-backed** implementation of the same `SessionMemory` interface. This is the v1→v2 replacement
for the global module-level `ConversationBufferMemory` (`legacy-code`) — no more shared global state across
requests; per-`session_id` isolation, TTL'd, correct for both guest and logged-in sessions at this phase
(Postgres persistence for logged-in users' durable history is **P2**, not this task).

Per the cross-cutting definition-of-done ("services never touch drivers directly") and the architecture
reviewer's note on P1-04, build the real repository seam now rather than another ad hoc Redis client:
- `app/repositories/redis.py` — the shared `redis.asyncio` **connection pool** (design §4: "single shared
  `ConnectionPool`... max 10 connections... shared across all requests and agents. Do not instantiate
  per-request `Redis()` clients; acquire via the repository layer only."). Provide a small accessor
  (e.g. `get_redis_pool(settings)` / a FastAPI dependency) that both this task's session memory and P1-02's
  router circuit-breaker can eventually share (wiring the router to use this same pool instead of its own
  ad hoc client from P1-04 is in scope if it's a small change — call out in `engineer.md` if you defer it).
- A Redis-backed `SessionMemory` implementation (e.g. `RedisSessionMemory` in `app/services/session_memory.py`
  or moved to `app/repositories/` if that fits the layering better — your call, document it) satisfying the
  existing `SessionMemory` ABC: `load(session_id) -> list[ChatMessage]`, `append(session_id, message)` (or
  whatever the P1-04 interface actually is — read it first).
- **TTL**: session working memory expires (design §4 "Active session working memory... including guest
  sessions"); pick a sensible default (e.g. 24h) via settings.
- Bound the stored history (design intent: recent turns, not unbounded) — cap to a reasonable number of
  messages or bytes so a long-running session_id doesn't grow Redis usage unbounded; document the policy.
- Wire `build_chat_service` (`app/api/chat.py`, from P1-04) to construct `RedisSessionMemory` instead of
  `InMemorySessionMemory`, using the shared pool from `app/repositories/redis.py`.
- Serialization: `ChatMessage` (P1-01 `app/llm/types.py`) → JSON in/out of Redis (list per session key, e.g.
  a Redis list or a JSON blob — your call, but keep it simple and documented).
- Tests: unit tests against a fake/in-memory Redis double (or `fakeredis` if already available/cheap to add
  — check `pyproject.toml` before adding a new dependency) covering: append + load round trip, TTL is set,
  history cap enforced, isolation between two different `session_id`s, and that `ChatService` (from P1-04)
  works unchanged against the new memory implementation (dependency-injection swap, not a rewrite of
  `ChatService`).

## Acceptance criteria
- [ ] `app/repositories/redis.py` provides the single shared `redis.asyncio` connection pool per design §4
      (no per-request `Redis()` instantiation elsewhere for this feature).
- [ ] A Redis-backed `SessionMemory` implementation satisfies the exact interface `ChatService` already
      depends on (from P1-04) — no changes needed to `ChatService`'s public contract.
- [ ] Two different `session_id`s never see each other's history (isolation verified in tests).
- [ ] Session memory has a TTL and a bounded size/turn cap (both configurable via `app/config.py`).
- [ ] `build_chat_service` uses the Redis-backed memory by default (the in-memory one may remain for tests).
- [ ] Unit tests pass against a fake/in-memory Redis double — no real Redis required in CI unless already
      available per the P0 CI setup (check `.github/workflows/backend-ci.yml` first).
- [ ] `ruff` + `mypy` clean.

## Design references
- dev-board/plan.md: Phase 1 ("Redis-backed per-session memory + cancel/stop (replaces global memory +
  in-process dict)")
- dev-board/app-design-and-features.md: §4 "Redis — ephemeral / hot path" (active session working memory
  including guest sessions; connection pooling: single shared `ConnectionPool`, max 10 connections, acquired
  only via the repository layer), §8 Target Project Structure (`repositories/redis.py`)
- dev-board/code-review/P1-04-chat-endpoint/engineer.md — the existing `SessionMemory` ABC / seam this task
  replaces, and `build_chat_service`'s current interim Redis client usage for the router circuit-breaker
- dev-board/code-review/P1-04-chat-endpoint/architecture-review.md — the follow-up note flagging that Redis
  session memory should land in `repositories/`

## Constraints / non-goals
- No Postgres persistence for logged-in users (that's P2 — "Persist P1 conversations to Postgres for
  logged-in users; guests stay Redis-only"). This task is Redis-only for **all** sessions at this phase.
- No cancel/stop endpoint (P1-06, next task) — though if the shared Redis pool from this task makes that
  task trivially easier later, that's fine; don't build the cancel endpoint itself here.
- No full Alembic/migration work (P2) — this is Redis, not Postgres.
- Don't rewrite `ChatService`'s tool-call loop; this is a memory-backend swap behind the existing interface.
