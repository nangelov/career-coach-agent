# Engineer report — P1-06-cancel-stream · Revision 1

## Summary
Implemented **`POST /api/chat/{session}/cancel`** — a **Redis-backed** stop/cancel signal that
replaces v1's in-process `active_requests` module dict (design §4 "Streaming/cancellation state";
§9 API surface). The endpoint sets a short-lived per-session flag and returns promptly (**202
Accepted**, never blocking on the stream); the in-flight `POST /api/chat` turn polls that flag at
its checkpoints and ends the SSE stream cleanly with a new terminal **`cancelled`** event.

Layering is preserved (Router → Service → Repository): the cancel endpoint is thin — it delegates to
`ChatService.request_cancel(session_id)`. `ChatService` owns both the request (setter) and the
poll/clear checks in its loop; the Redis flag store (`RedisCancelRegistry`) lives in the repository
layer behind a `CancelRegistry` port (interface-before-implementation), mirroring the P1-05
`SessionMemory`/`RedisSessionMemory` split. `LLMRouter`'s public contract is untouched — the cancel
check lives in `ChatService`'s loop around the router calls (as the task preferred).

## Files changed
- `app/schemas/chat.py` — **new event** `CancelledEvent` (`event: "cancelled"`, carries
  `message_id`), added to the `ChatEvent` union and the documented SSE vocabulary. This is the
  terminal event P1-08's stop button consumes.
- `app/services/cancellation.py` — **new.** `CancelRegistry` ABC (the port: `request` / `is_requested`
  / `clear`) + `InMemoryCancelRegistry` (process-local default / test double). Mirrors the
  `session_memory.py` seam.
- `app/repositories/redis.py` — **new** `RedisCancelRegistry` (implements `CancelRegistry`) + the
  `CancelRedis` structural `Protocol` (minimal `set`/`exists`/`delete` surface so tests inject a fake).
  Stores flag at `session:cancel:<session_id>` with a short TTL.
- `app/repositories/__init__.py` — export `CancelRedis`, `RedisCancelRegistry`.
- `app/config.py` — new `CHAT_CANCEL_TTL_SECONDS` (default 60) — the flag's leak-backstop TTL.
- `app/services/chat.py` — `ChatService` gains an injected `cancel: CancelRegistry` (defaulted), a
  public `request_cancel()`, iteration-boundary + every-N-chunks cancel polling, partial-answer
  persistence, deterministic router-stream close on early cancel, and a `_finish_cancelled` helper.
- `app/api/chat.py` — `build_chat_service` now also builds `RedisCancelRegistry` from the **same**
  shared Redis client (one more cast at the single composition-root boundary) and injects it; **new**
  `POST /chat/{session}/cancel` route (202).
- `tests/test_chat_cancel.py` — **new.** 11 tests (registry unit tests with a fake `CancelRedis`;
  service cancel behaviour; endpoint delegation/promptness).

No changes to `llm/*` (router untouched) or `tools/*`.

## Key decisions
- **Distinct `cancelled` terminal event** (not `done` with `finish_reason="cancelled"`). Chosen from
  the two task-offered options: it keeps `finish_reason` meaning *the model's own* reason, and lets the
  UI render a user-stopped turn distinctly from a natural completion. Terminal like `done`/`error`, and
  carries `message_id` so any partial answer stays attributable/feedback-ready (§5.5 / P1-07).
  Documented verbatim in `schemas/chat.py` for P1-08.
- **Cancel check granularity.** The loop polls the flag (a) once at each **iteration boundary** (catches
  a cancel that lands between tool round-trips, before the next model call) and (b) **every N=8 streamed
  chunks** inside a single completion (bounds cancel latency to a few tokens on a long single generation
  without a Redis round-trip per token). `N` is a `ChatService` param (`cancel_check_interval`); TTL is
  a setting.
- **Leak safety — three layers**, so a stale flag never wrongly cancels a *future* request on the same
  `session_id`: (1) **short TTL** on the key (self-expires if no stream ever observes it — e.g. cancel
  raced a just-finished turn); (2) **observed → deleted** (the loop clears the flag the instant it acts);
  (3) **fresh-turn clear** (`stream_turn` drops any stale flag before streaming, so a turn is never born
  cancelled). Test `test_stale_flag_is_cleared_at_turn_start` pins layer 3.
- **Partial-answer persistence.** On a mid-completion cancel, the partial assistant content streamed so
  far is appended to session memory alongside the user message (and any completed tool round-trips), so
  the next turn stays coherent — same `turn.produced` persistence path the iteration-cap case already
  uses.
- **Deterministic stream close.** On an early cancel return, `_run_iteration` closes the router's async
  generator in `finally` (best-effort `getattr(stream, "aclose", None)`) so the upstream stream/HTTP
  connection is released promptly rather than at GC. Used `try/finally` + `getattr` rather than
  `contextlib.aclosing` because the router's declared `AsyncIterator` return type fails mypy's `aclosing`
  type-var (the runtime object is a generator, but the type doesn't say so) — and the router's public
  seam is deliberately not widened.
- **Same shared Redis client (§4).** The cancel registry acquires the *one* client from the P1-05
  `RedisConnectionProvider` pool — no new pool/client. Both chat endpoints resolve the same app-scoped
  `ChatService` via `get_chat_service`, so cancel and the in-flight stream share one registry instance.
- **202 Accepted** for the cancel endpoint — semantically "accepted, processing async"; matches "returns
  promptly without waiting on the stream". Idempotent: cancelling an idle session is a 202 no-op (flag
  TTL-expires).

## How to verify
From `backend/` (curated env: fastapi/pydantic/openai/redis present — redis via `celery[redis]`):
```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy app/
.venv/bin/python -m pytest -q
```
Results (local `.venv`):
- `ruff check .` → `All checks passed!`
- `ruff format --check .` → `43 files already formatted`
- `mypy app/` → `Success: no issues found in 31 source files`
- `pytest -q` → `62 passed` (51 prior + 11 new)

New tests (`tests/test_chat_cancel.py`) cover the acceptance criteria: registry set-with-TTL / poll /
clear / isolation / settings TTL; **cancel mid-stream → partial tokens then a terminal `CancelledEvent`,
flag cleared, partial answer persisted**; **cancel between tool round-trips → stops before the 2nd model
call**; a turn with no cancel completes with `DoneEvent`; **two `session_id`s never cross-cancel**; a
stale flag is cleared at turn start; **the cancel endpoint returns 202 promptly and delegates** without
opening any stream.

**Manual live check** (real Redis + HF token): start a long `POST /api/chat` stream (`curl -N ...`), then
in another shell `curl -X POST http://localhost:8000/api/chat/demo/cancel` — the first stream ends with
`event: cancelled` within a few tokens; `redis-cli GET session:cancel:demo` shows the key gone (cleared
on observation) or TTL-bounded.

## Self-check
- [x] `POST /api/chat/{session}/cancel` sets a Redis-backed flag and returns promptly (202, no stream
  wait) — `test_cancel_endpoint_returns_promptly_and_delegates`.
- [x] In-flight stream observes the flag and stops within a bounded number of chunks/iterations, ending
  cleanly with the documented terminal `cancelled` event, no hung connection / no unhandled exception.
- [x] Cancelling one session never affects another (`test_cancel_does_not_cross_sessions`).
- [x] Flags don't leak across future requests — TTL + observed-delete + fresh-turn clear
  (`test_stale_flag_is_cleared_at_turn_start`).
- [x] `LLMRouter` public contract unchanged — cancel logic lives in `ChatService`'s loop.
- [x] Unit tests pass with a fake Redis double — no real Redis / HF network in CI.
- [x] `ruff` + `mypy --strict` clean (output pasted); layering Router→Service→Repository respected
  (endpoint thin; port in `services/`, adapter in `repositories/`).
- [x] No secrets committed; TTL via `app/config.py`.

## Notes for reviewers
- **Known gap (by design, P3):** no auth/ownership on cancel — anyone who knows a `session_id` can cancel
  it. Flagged in the endpoint docstring and `RedisCancelRegistry`; per-session/user access control +
  rate limits are the P3 AuthZ task's job (task constraint).
- **Router deep-block caveat:** if the active model were stuck inside one long *non-yielding* call, the
  per-chunk check can't fire until a chunk arrives — but the router already streams incrementally and has
  its own first-token/timeout deadlines (§6.6), so in practice chunks flow and the check runs. Not worth
  reworking the router seam (task guidance) — flagged, not solved.
- **SSE vocabulary is now:** `start` · `token` · `tool_call` · `tool_result` · `done` · **`cancelled`**
  (new, terminal, `{message_id}`) · `error`. P1-08 consumes `cancelled` verbatim.
