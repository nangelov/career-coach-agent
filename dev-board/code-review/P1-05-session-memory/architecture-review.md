# Architecture review — P1-05-session-memory · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Redis store + shared pool live in `repositories/redis.py`; service depends only on the port | `RedisConnectionProvider` + `RedisSessionMemory` in `app/repositories/redis.py`; `SessionMemory` ABC stays in `app/services/session_memory.py` | None — matches the P1-04 arch follow-up and the prior placement ruling (adapter in `repositories/`, port in `services/`) |
| A2 | Layering (Router→Service→Repo) | Services never touch a driver directly | `ChatService` depends only on the `SessionMemory` ABC; the Redis adapter is injected at the composition root (`build_chat_service`); no `redis` import in `services/` | None |
| A3 | §4 connection pooling | Single shared `redis.asyncio` `ConnectionPool`, max 10, acquired only via the repository layer; no per-request `Redis()` | One `ConnectionPool.from_url(..., max_connections=REDIS_MAX_CONNECTIONS=10)`; one shared `Redis` client handed to both the router breaker and session memory | None — this also retires P1-04's ad hoc `from_url` client (the pool is now shared, as the task invited) |
| A4 | §4 ephemeral/hot-path ownership | Active session working memory (incl. guests) lives in Redis, TTL'd, recent turns only | List per `session:mem:<session_id>`, sliding `EXPIRE` (default 24h), `LTRIM` cap (default 100), both in `app/config.py` | None |
| A5 | Phase fit (P1 vs P2) | Redis-only for all sessions this phase; Postgres durable history is P2; no premature coupling | Redis-only for guest + logged-in alike; no Postgres/Alembic touched | None — foundation-first respected |
| A6 | Interfaces-before-impl | Real swap seam behind the port | `SessionMemory` ABC unchanged; `SessionRedis` `Protocol` mirrors the router's `RedisLike`; cast confined to the one composition-root boundary | None |
| A7 | Locked decisions | Postgres + Redis only; no Mongo; no ReAct parser; budget free/OSS | Redis-only change; hand-rolled fake (no new dep added for tests) | None |
| A8 | §4 data-ownership / trust boundary | Server-side memory is canonical once it lands; session state is server-owned | `stream_turn` still lets client-supplied `history` **fully override** the now-canonical Redis memory (`chat.py:109` → `chat.py:155`), and accepts `system`/`tool` roles + forged `tool_calls` | Follow-up (not a blocker) — see Notes N1; deferred to P3 per engineer, consistent with the P1-04 note |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — store in `repositories/`, port in `services/`, wiring at the composition root
- [x] Honors locked decisions (no ReAct parser; Postgres+Redis only; in-process embeddings untouched; SSO not regressed)
- [x] Interfaces-before-implementations (`SessionMemory` ABC, `SessionRedis`/`RedisLike` protocols, `RedisConnectionProvider`)
- [x] Budget posture respected (self-hosted Redis; tests use an in-memory fake, no `fakeredis`/paid dep added)

## Notes
- **N1 (design risk, follow-up — escalated, not a blocker for this task).** Now that Redis session memory is
  canonical, `POST /api/chat` still accepts a client-supplied `history` that *replaces* the server-side store
  (`prior = list(history) if history is not None else await self._memory.load(session_id)`), and that history
  may carry `role="system"`/`role="tool"` with fabricated `tool_calls`. This is a §4 data-ownership seam: a
  client can supplant server-owned conversation state and inject a system prompt / forge tool results. It is
  **pre-existing from P1-04** (blessed there for the unauthenticated walking skeleton) and *not worsened* by this
  task — the memory-backend swap is correctly scoped and the endpoint contract was deliberately left untouched
  (a stated non-goal). The endpoint is also not yet auth-gated, so full session-ownership enforcement genuinely
  belongs with auth. Cheap to unwind later (a schema validator constraining accepted `history` to
  `user`/`assistant` + preferring/merging server memory over client `history`), so it does not gate this task.
  **Required by P3 at the latest** — constrain accepted client `history` to `user`/`assistant` content and reject
  client-supplied `system`/`tool` roles and `tool_calls`. Logging here so it is not lost between phases; the
  injection/security dimension is the code-reviewer's gate, the data-ownership dimension is mine.
- **N2 (accepted).** The count-based `LTRIM` cap can split an assistant `tool_call` / `tool` result pair at the
  boundary for a conversation longer than `SESSION_MEMORY_MAX_MESSAGES`. Documented in the docstring and matches
  the interim store; a turn-aware cap is a fine future refinement, not a P1 design requirement.
- **N3 (good).** `RedisConnectionProvider` is owned by the composition root and closed once in the lifespan
  (single owner; the router's `aclose` closes only LLM clients), so there is no double-close of the shared pool.
