# Engineer report — P1-04-chat-endpoint · Revision 1

## Summary
Wired the first real end-to-end path: **`POST /api/chat`** streaming over SSE, driven by a
model-tool-call loop (design §9; plan.md Phase 1 "walking skeleton — no multi-agent yet").

The endpoint is thin (Router → Service → Agent/Repository): `app/api/chat.py` only validates the
request and adapts a typed event stream to the SSE wire format. All the loop logic lives in
`ChatService` (`app/services/chat.py`), which:

1. loads prior turns for the session, appends the new user message,
2. streams a completion from the **P1-02 `LLMRouter`** with the **P1-03 registry's** tool schemas,
   emitting `token` events as content flows and reassembling any streamed `tool_calls`,
3. if tools were requested → emits `tool_call`/`tool_result`, appends the assistant + tool messages
   (via `registry.execute()`), and loops,
4. if a plain answer → persists the turn and emits `done`,
5. caps iterations (default 5) to stop runaway tool loops, and turns
   `LLMAllModelsFailedError` (or any unexpected error) into a **single terminal `error` event** — no
   unhandled mid-stream 500.

No ReAct/text parsing anywhere — the loop is entirely native-tool-calling on `StreamChunk` deltas.

## Files changed
- `app/schemas/chat.py` — **new.** `ChatRequest` + the streamed-event union (`StartEvent`,
  `TokenEvent`, `ToolCallEvent`, `ToolResultEvent`, `DoneEvent`, `ErrorEvent`) and `ChatEvent`. This
  is the authoritative SSE vocabulary P1-08's Next.js page consumes.
- `app/services/session_memory.py` — **new.** `SessionMemory` ABC + `InMemorySessionMemory` — the
  narrow interim seam P1-05 replaces with a Redis-backed store behind the same interface.
- `app/services/chat.py` — **new.** `ChatService` (the model⇄tools loop) + private
  `_ToolCallAccumulator` (reassembles streamed tool calls), `_Turn`, `_IterationResult`.
- `app/api/chat.py` — **new.** `POST /api/chat` `StreamingResponse` (`text/event-stream`),
  `get_chat_service` dependency (lazy-built + cached on `app.state`, overridable in tests),
  `build_chat_service`, `_format_sse`.
- `app/main.py` — include the chat router; close a lazily-built chat service on shutdown.
- `tests/test_chat_service.py` — **new.** Service-level tests with fake router/registry (plain
  answer + streaming + memory replay, tool round trip, iteration cap, all-models-failed).
- `tests/test_chat_api.py` — **new.** API smoke tests: SSE framing via dependency override, and 422
  on empty message.

No changes to `llm/*` or `tools/*` — they were consumed through their existing public surfaces.

## Key decisions
- **Interim session-memory seam (task requirement).** `SessionMemory.load/append` keyed by
  `session_id`; `InMemorySessionMemory` is process-local. The endpoint's public contract is
  `ChatRequest{session_id, message}` — **P1-05 swaps in a Redis-backed `SessionMemory` with zero
  endpoint change.** (`ChatRequest.history` is an optional stateless escape hatch; when omitted,
  server-side memory is the source of truth.) **P1-05: replace `InMemorySessionMemory`; the
  interface and the `ChatService(memory=...)` injection point are the swap seam.**
- **Service owns the loop; router stays HTTP-free.** `ChatService.stream_turn` yields
  `ChatEvent`s; `api/chat.py` is the only place that serialises to SSE (`_format_sse`). This keeps
  the cross-cutting layering rule (Router→Service→Agent/Repo).
- **Token-by-token streaming preserved.** `_run_iteration` is an async generator that yields each
  `TokenEvent` the instant a content delta arrives (results returned via an out-param dataclass
  since async generators can't `return` a value) — content is never buffered until end-of-turn.
- **Streamed tool-call reassembly.** Providers stream `tool_calls` piecewise by `index`;
  `_ToolCallAccumulator` merges `id`/`name`/`arguments` fragments, then `registry.execute()` runs
  the documented round trip (P1-03) and returns a `role="tool"` message appended for the next model
  step.
- **SSE vocabulary** (verbatim for P1-08): `start`{message_id} · `token`{content} ·
  `tool_call`{id,name,arguments} · `tool_result`{tool_call_id,name,content} ·
  `done`{message_id,finish_reason} · `error`{message}. Frame = `event: <name>\ndata: <json>\n\n`.
  `text/event-stream` opts the response out of gzip (Starlette 1.3.1 excludes it) so tokens aren't
  buffered; also sets `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
- **Iteration cap = clean terminal error.** After `max_iterations` model round-trips still asking for
  tools, the loop stops and emits an `error` event (no infinite loop, no partial 500).
- **Failure handling.** `LLMAllModelsFailedError` → "temporarily unavailable" `error`; other
  `LLMError` and any unexpected `Exception` → generic `error` (logged). The stream always ends
  cleanly.
- **`message_id`** = a per-assistant-message UUID (hex), emitted on `start` and repeated on `done`.
  **P1-07 formalizes** the stable, feedback-ready semantics (§5.5) on top of this.
- **Lazy DI for P1.** `build_chat_service` constructs the router (with a `redis.asyncio` client
  satisfying the router's `RedisLike` seam — `from_url` is lazy, no I/O until first request), the
  P1-03 default registry, and in-memory session store; cached on `app.state`, closed on shutdown.
  **P2 moves construction to the shared connection pools** (this is the interim owner).

## How to verify
From `backend/` (curated env: fastapi/pydantic/openai/redis present):
```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy app/
.venv/bin/python -m pytest -q
```
Results (local `.venv`):
- `ruff check .` → `All checks passed!`
- `ruff format --check .` → `39 files already formatted`
- `mypy app/` → `Success: no issues found in 29 source files`
- `pytest -q` → `41 passed` (34 prior + 7 new)

**SSE frame shape** (rendered via `_format_sse`, no network):
```
event: start
data: {"message_id": "abc"}

event: token
data: {"content": "Hello"}

event: tool_call
data: {"id": "call_1", "name": "current_date_and_time", "arguments": "{}"}

event: tool_result
data: {"tool_call_id": "call_1", "name": "current_date_and_time", "content": "{\"now\":\"noon\"}"}

event: done
data: {"message_id": "abc", "finish_reason": "stop"}
```

**Manual live test against a running instance** (real HF token + a running Redis, e.g. from
docker-compose): set `HF_API_TOKEN`, `DATABASE_URL`, `JWT_SECRET_KEY`, `REDIS_URL`, then:
```bash
uvicorn app.main:app --port 8000
curl -N -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"What is the date and time in Sofia right now?"}'
```
`-N` disables curl buffering; you should see `event: start`, then `token` frames arriving
incrementally, a `tool_call`/`tool_result` pair for `current_date_and_time`, more `token` frames, and
a final `done`. (Not automated — needs a real HF endpoint + token.)

## Self-check
- [x] `POST /api/chat` streams tokens over SSE (token-by-token; verified via frame shape + service
  test asserting per-delta `TokenEvent`s; manual `curl` documented above).
- [x] Model can call a registered tool mid-conversation, loop executes it, final answer reflects the
  result (`test_tool_call_round_trip`).
- [x] Layering respected — `api/chat.py` thin (validate + SSE); loop lives in `app/services/chat.py`.
- [x] Iteration cap prevents runaway loops (`test_iteration_cap_stops_runaway_tool_calls`).
- [x] All-models-failed → clean terminal SSE `error`, no 500 (`test_all_models_failed...`); broad
  `except` guards any other mid-stream error too.
- [x] Every assistant message carries a `message_id` UUID (start ↔ done; P1-07 formalizes).
- [x] Unit tests pass with fakes/doubles — no real HF/Redis network.
- [x] `ruff` + `mypy --strict` clean (output pasted).
- [x] No secrets committed; all config via `settings` (env / Space secrets).

## Notes for reviewers
- **`ToolResultEvent` omits `is_error`.** `registry.execute()` (the documented P1-03 API) returns a
  `role="tool"` `ChatMessage`, which does not carry `ToolResult.is_error`. Rather than fragile
  JSON-sniffing, the event exposes the tool's raw JSON `content` (graceful tool errors are already a
  `{"error": ...}` payload the model/UI can read). If a first-class error flag is wanted, that's a
  small registry API addition — flagged rather than hacked.
- **P1 scope kept tight:** no LangGraph/multi-agent (P4), no Redis-backed session memory (P1-05, seam
  ready), no cancel endpoint (P1-06), no feedback/message_id formalization (P1-07), no frontend
  (P1-08 — SSE vocab documented above verbatim).
- Interim `build_chat_service` owns a `redis.asyncio` client for the router's circuit-breaker; this
  is explicitly the P1 stand-in until P2 wires the shared pool (`repositories/redis.py`, §4).
