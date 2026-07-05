# Architecture review — P1-06-cancel-stream · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 target structure | Port (interface) in `services/`, concrete Redis store in `repositories/`; API in `api/`; event contract in `schemas/` | `CancelRegistry` ABC + `InMemoryCancelRegistry` in `app/services/cancellation.py`; `RedisCancelRegistry` in `app/repositories/redis.py`; route in `app/api/chat.py`; `CancelledEvent` in `app/schemas/chat.py` | None — matches the blessed [[ruling-session-memory-placement]] split exactly |
| A2 | Layering (Router→Service→Repository) | Thin endpoint delegating to service; service owns loop; no datastore driver in service | `cancel_chat` delegates to `ChatService.request_cancel`; service polls the port, never touches Redis directly; Redis client resolved only at the composition root | None |
| A3 | Interface-before-implementation | Cancel signal behind a real seam, swappable store | `CancelRegistry` ABC + structural `CancelRedis` Protocol; service depends only on the ABC; fake injected in tests | None |
| A4 | §9 API surface | `POST /api/chat/{session}/cancel` "Stop generation — Redis-backed (was in-process dict)" | Route `/chat/{session}/cancel` under `/api` prefix, 202, sets Redis flag, returns promptly | None — path and semantics match §9 line 396 |
| A5 | §4 data ownership | Streaming/cancellation state in Redis (ephemeral/hot path), replaces v1 `active_requests` dict | Flag at `session:cancel:<session_id>` with TTL; v1 module dict removed | None — matches §4 line 169 |
| A6 | Shared connection pool (§4) | No per-feature `Redis()`; acquire from the one `RedisConnectionProvider` pool | Cancel registry uses the same client from the P1-05 provider; single cast at composition root | None |
| A7 | Locked decision — datastores | Postgres + Redis only, self-hosted; no MongoDB, no managed tier | Redis only; no new store introduced | None |
| A8 | Locked decision — `LLMRouter` contract | Failover router untouched; cancel lives in service loop | `llm/*` unchanged; cancel check wraps router calls in `ChatService` | None |
| A9 | Phase fit (P1 walking skeleton) | No premature LangGraph/multi-agent coupling; auth deferred to P3 | Loop stays in `ChatService`; no-auth gap documented as P3 owner's job | None — consistent with [[pattern-p1-walking-skeleton]] |
| A10 | SSE vocabulary | Authoritative in `schemas/chat.py`; P1-08 consumes verbatim | `cancelled` added to `ChatEvent` union, documented terminal event with `message_id` | None — clean extension of the P1-04 vocabulary |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Repository)
- [x] Honors locked decisions (Redis-only; no ReAct parser; router untouched; SSO/auth correctly deferred to P3)
- [x] Interfaces-before-implementations (`CancelRegistry` port + `RedisCancelRegistry` adapter + `CancelRedis` Protocol)
- [x] Budget posture respected (self-hosted Redis, no paid service)

## Notes
- The concrete-store-in-`repositories`, ABC-in-`services` placement mirrors P1-05 exactly and honors the standing
  ruling — no re-litigation needed. This is the pattern I want future Redis/Postgres-backed stores to follow.
- Auth/ownership gap on the cancel endpoint is a **deliberate, documented P3 deferral** (§9/§3), not a design
  deviation. Flagged so the P3 AuthZ task closes it (per-session/user access control + rate limits). No action now.
- Design risk (already-logged, not new): the lazy composition root in `api/chat.py` (`build_chat_service`)
  remains a P1 stand-in — P2 owns moving the remaining composition to shared pools. This task correctly acquires
  the cancel registry's client from the *existing* shared provider rather than adding a new pool, so it does not
  deepen the debt.
- Minor future refinement (not a gate): the `finally`-block `getattr(stream, "aclose", ...)` is a pragmatic way
  to avoid widening the router's `AsyncIterator` seam — acceptable and the right call for keeping P1-02's public
  contract stable.
