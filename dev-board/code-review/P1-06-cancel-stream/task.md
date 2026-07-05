# Task P1-06-cancel-stream — Redis-backed cancel/stop for in-flight chat streams
- **Phase:** P1   **Status:** ENG   **Tags:** (B)

## Scope
Implement `POST /api/chat/{session}/cancel` (design §9: "Stop generation — Redis-backed (was in-process
dict)"). This replaces v1's `active_requests` module-level dict (`legacy-code`) with a **Redis-backed**
cancellation signal, consistent with the shared connection-pool work already landed in P1-05
(`app/repositories/redis.py` — `RedisConnectionProvider`).

Design:
- On `POST /api/chat/{session}/cancel`, set a short-lived Redis key/flag scoped to that `session_id` (e.g.
  `session:cancel:<session_id>`), then return promptly (this endpoint does not block waiting for the stream
  to actually stop).
- `ChatService`'s tool-call loop (`app/services/chat.py`, from P1-04) must **check the cancel flag** at each
  natural checkpoint of the loop (e.g. before each iteration, and ideally between streamed token chunks so a
  long single-iteration generation can also stop promptly — use judgement on granularity vs. overhead; a
  check per-chunk or every N chunks is reasonable) and, if set, stop generating and end the SSE stream
  cleanly with a terminal event (e.g. a `done` event with `finish_reason="cancelled"`, or add a distinct
  `cancelled` event to the P1-04 SSE vocabulary — pick one and document it clearly since P1-08's frontend
  depends on it).
- Clear/expire the cancel flag appropriately (TTL so a stale flag from a finished stream doesn't leak into a
  *future* request on the same `session_id`; and/or delete it once the in-flight stream observes it).
- This must work across the failover boundary from P1-02 (`LLMRouter`) — cancellation should stop the loop
  regardless of which model in the router's list is currently serving; you don't need to touch `LLMRouter`
  itself if the cancel check lives in `ChatService`'s loop around the router calls (preferred, keeps P1-02
  untouched) — but if you find a case where the router needs to cooperate (e.g. it's blocked deep inside a
  long single non-yielding call), document the tradeoff rather than reworking the router's public contract
  without discussion.
- Auth/ownership is **not** enforced yet (no real auth until P3) — anyone who knows a `session_id` can cancel
  it for now; note this explicitly as a known gap the P3 AuthZ task must close (per-session/user rate limits
  + access control land there).
- Tests: unit tests with a fake Redis double (reuse the `SessionRedis`-style protocol/fake pattern from
  P1-05 if it fits) covering: cancel flag set → an in-progress fake stream stops and emits the terminal
  cancelled/done event; a stream that finishes before cancel is requested is unaffected; two different
  `session_id`s don't cross-cancel; the cancel endpoint returns promptly without waiting on the stream.

## Acceptance criteria
- [ ] `POST /api/chat/{session}/cancel` sets a Redis-backed cancel signal for that session and returns
      promptly (no blocking on the actual stream).
- [ ] An in-flight `POST /api/chat` stream for that same `session_id` observes the signal and stops within a
      bounded number of loop iterations/chunks, ending the SSE stream cleanly (documented terminal event, no
      hung connection, no unhandled exception).
- [ ] Cancelling one session never affects another session's in-flight stream.
- [ ] Cancel flags don't leak across unrelated future requests (TTL and/or explicit cleanup).
- [ ] No changes to `LLMRouter`'s public contract unless justified and documented.
- [ ] Unit tests pass with a fake Redis double — no real Redis required in CI.
- [ ] `ruff` + `mypy` clean.

## Design references
- dev-board/plan.md: Phase 1 ("Redis-backed per-session memory + cancel/stop (replaces global memory +
  in-process dict)")
- dev-board/app-design-and-features.md: §9 API Surface (`POST /api/chat/{session}/cancel`), §4 "Redis —
  ephemeral / hot path" ("Streaming/cancellation state — replaces v1's in-process `active_requests` dict")
- dev-board/code-review/P1-04-chat-endpoint/engineer.md — `ChatService`'s loop, the SSE event vocabulary
  you're extending/reusing for the cancelled case
- dev-board/code-review/P1-05-session-memory/engineer.md — `RedisConnectionProvider`, the shared-pool /
  structural-Protocol-plus-cast pattern for Redis access

## Constraints / non-goals
- No real authentication/authorization on the cancel endpoint (P3) — note the gap, don't attempt to solve it
  here.
- No frontend stop-button wiring (that's P1-08) — though document the terminal SSE event shape clearly since
  the frontend task consumes it verbatim.
- Don't rework `LLMRouter`'s public interface without clearly documenting why it was unavoidable.
