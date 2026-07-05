# Architecture review — P1-04-chat-endpoint · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Router in `api/chat.py`, loop in `services/`, request/event models in `schemas/` | `app/api/chat.py` (thin SSE), `app/services/chat.py` (loop), `app/schemas/chat.py` (`ChatRequest` + event union), `app/services/session_memory.py` (seam) — all in the right modules | none |
| A2 | Layering (Router→Service→Agent/Repo) | Router thin (req/resp + SSE); service owns loop; no HTTP/SSE in service | `api/chat.py` only validates + `_format_sse`; `ChatService.stream_turn` yields typed `ChatEvent`, knows nothing of SSE; `_format_sse` is the sole serialiser | none |
| A3 | §9 API surface | `POST /api/chat` streaming SSE, replaces `/agent/query`, per-session memory | `APIRouter(prefix="/api")` + `/chat` → `POST /api/chat`, `StreamingResponse` `text/event-stream`, `session_id`-keyed memory | none |
| A4 | Native tool-calling, no ReAct parser (§6/§6.6; locked v2) | Model-driven native `tool_calls` loop; no text parser | Loop reads `StreamChunk`/`ToolCallDelta`, reassembles by `index`, executes via `registry.execute()`; zero text parsing | none |
| A5 | Phase fit — "no multi-agent yet" (plan P1) | Simple in-endpoint loop, no LangGraph/`agents/graph.py` | Single `ChatService` loop; `agents/` untouched; iteration cap = 5 (v1 `max_iterations` spirit) | none |
| A6 | Datastores: Postgres+Redis only, no Mongo (locked v2) | No new datastore engines; interim history seam narrow | `InMemorySessionMemory` process-local interim; Redis client only for the router circuit-breaker; no Mongo/other engines | none — but see A7 (placement) |
| A7 | Data access lives in `repositories/` (§4/§8) | Persistent stores accessed via repositories layer | `SessionMemory` ABC + in-memory impl currently in `services/`; interface is storage-agnostic | Follow-up (not blocking): P1-05 must land the **Redis-backed** `SessionMemory` in `repositories/redis.py` (§4/§8), with services depending on the ABC — do not put the Redis store in `services/`. |
| A8 | message_id foundation (§5.5, formalized P1-07) | Some stable id per assistant message now | Per-message UUID (`uuid4().hex`) emitted on `start`, echoed on `done`; noted P1-07 formalizes | none |
| A9 | Reliability failover present where needed (§6.6; locked v2) | Loop uses `LLMRouter` (failover), terminal error on exhaustion | `ChatService` streams via `LLMRouter`; `LLMAllModelsFailedError` → single terminal `error` event, no mid-stream 500 | none |
| A10 | Budget posture (§11) | free/OSS/self-hosted | In-process loop, no paid deps introduced | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — router thin, service owns loop, schemas/seam correctly placed (A7 is a P1-05 placement follow-up, not a P1 gap)
- [x] Honors locked decisions (native tool-calling, no ReAct parser; Postgres+Redis only, no Mongo; in-process — no new engines; LangGraph correctly deferred to P4)
- [x] Interfaces-before-implementations — `SessionMemory` ABC is a clean swap seam; `ChatService` takes `LLMRouter`/`ToolRegistry`/`SessionMemory` by injection
- [x] Budget posture respected (free/OSS/self-hosted)

## Notes
- **Design risk (follow-up, flag to P1-05 / P3-auth): the `ChatRequest.history` escape hatch accepts a full
  `list[ChatMessage]`** — including `role="system"` and `role="tool"` with fabricated `tool_calls`. A client
  can therefore inject a system prompt or forge tool results, bypassing server-owned conversation state (§4
  data ownership). Acceptable for the P1 walking skeleton (endpoint is not yet auth-gated — auth is P3, Redis
  memory is P1-05), but when P1-05 makes server-side session memory canonical, the accepted client `history`
  should be constrained to `user`/`assistant` content (no `system`/`tool` roles, no client-supplied
  `tool_calls`). The security/injection angle is the code-reviewer's to gate; noted here for the
  data-ownership/trust-boundary dimension.
- **`DEFAULT_SYSTEM_PROMPT` is hardcoded in `services/chat.py`.** Fine for the skeleton; the engineer correctly
  notes prompt sourcing/engineering lands with the multi-agent graph in P4. Logged so it isn't lost.
- **SSE event vocabulary** (`start`/`token`/`tool_call`/`tool_result`/`done`/`error`) is a new, well-documented
  contract not pre-specified in the design — the task delegated this to the implementation, and it is captured
  authoritatively in `schemas/chat.py` + `engineer.md` for P1-08 to consume verbatim. No conformance issue.
- **`ToolResultEvent` omits an error flag** (engineer note): reasonable given the P1-03 `registry.execute()`
  returns a `role="tool"` `ChatMessage` without `ToolResult.is_error`. A first-class error flag would be a
  small registry API addition, not something to hack in here — no design objection to deferring it.
- **Interim DI in `api/chat.py`** (`build_chat_service` constructs router + Redis client + registry) is a
  composition-root stand-in explicitly scoped to P1; §4/§8 shared-pool ownership moves to P2. Acceptable and
  clearly documented as such.
