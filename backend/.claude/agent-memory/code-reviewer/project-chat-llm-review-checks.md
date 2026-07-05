---
name: project-chat-llm-review-checks
description: Recurring correctness/security checks for the v2 chat/LLM/tool-loop code (P1+) — SSE injection, client-supplied history trust, lazy-DI races, native-tool-only, terminal-event discipline
metadata:
  type: project
---

Checks that repeatedly matter when reviewing the v2 backend chat/LLM/tool code (`app/api/chat.py`, `app/services/chat.py`, `app/llm/*`, `app/tools/*`).

**Why:** v2 streams SSE, drives a native model⇄tools loop, and uses interim in-memory seams before Redis/Postgres land — each has a predictable failure class worth checking every task.

**How to apply:**
- **SSE frame injection:** confirm token/tool content is JSON-encoded (`json.dumps`) before hitting the `event:`/`data:` wire — never raw-interpolated. Raw content with newlines would forge frames.
- **Client-supplied history trust:** any request field that seeds the LLM message list (e.g. `ChatRequest.history: list[ChatMessage]`) lets a client inject `role="system"`/`role="tool"` and steer the model or pre-empt P10 guardrails. Flag it; recommend restricting roles or dropping the escape hatch. Impact is self-scoped (own session) so it's usually `minor`, not gating — but carry it into P10.
- **Lazy DI on `app.state`:** `get_*_service` that builds-and-caches without a lock races on concurrent first requests → duplicate clients (Redis/HTTP), only one closed on shutdown → leak. Interim-acceptable; flag for P2 pool wiring.
- **Native-tool-only (locked decision):** there must be NO ReAct/text-parsing of model output — the v1 `output_parser.py` path is deleted in v2. Tool calls come via `tool_calls` deltas reassembled by `index`.
- **Terminal-event discipline:** every stream path must end in exactly one `done` OR one `error` — no unhandled mid-stream 500. Check that the broad `except Exception` (BLE001) is present AND that it does not swallow `asyncio.CancelledError` (it doesn't — CancelledError is BaseException in 3.11, so client-disconnect still cancels).
- **Interim memory persistence asymmetry:** watch which exit paths persist `turn.produced` (success/cap) vs drop it (errors), and whether client `history` + server `SessionMemory` can diverge. Usually `nit`/`minor`, but note it so P1-05 (Redis session store) doesn't inherit ambiguity.
- **Redis multi-command write atomicity + TTL-drop (P1-05 `RedisSessionMemory.append`):** a `rpush`→`ltrim`→`expire` sequence that is NOT pipelined/`MULTI` can interleave under concurrency AND, if it dies after `rpush` before `expire`, leaves a **no-TTL leaked key**. Flag `minor` for P1, recommend `pipeline(transaction=True)`/Lua for P2. Check every new Redis write path for this.
- **Redis-backed cancel/stop (P1-06 `CancelRegistry`/`RedisCancelRegistry` + `ChatService` cancel poll):** verify (a) the endpoint sets the flag and returns promptly (202, no stream wait), (b) leak safety is layered — short TTL + observed-delete + a *fresh-turn clear* at `stream_turn` start so a turn is never born cancelled, (c) the cancel check lives in `ChatService`'s loop (iteration boundary + every-N-chunks), leaving `LLMRouter` untouched, and (d) partial-answer persistence on mid-stream cancel doesn't create an orphan `role="tool"` (partial tool-call deltas must be dropped un-executed). Two accepted design tradeoffs (note, don't gate): a cancel arriving during a completion **shorter than `cancel_check_interval`** lands as `done` not `cancelled` (bounded/tiny); and the fresh-turn clear means cancel can't stop a *different concurrent* turn on the same `session_id` — flag for P1-08's frontend.
- **Count-cap splitting tool-call pairs (`LTRIM -N -1` on session history):** a naive message-count cap can drop an assistant `tool_calls` msg while keeping its `role="tool"` reply → next `load` returns an orphan `tool` msg → OpenAI-compatible API 400s → a session that stays broken until it ages out. Currently documented + deferred (turn-aware cap); note it, don't gate at P1.

Verify commands (run from `backend/`): `.venv/bin/ruff check .` · `.venv/bin/mypy app/` · `.venv/bin/python -m pytest -q`.
