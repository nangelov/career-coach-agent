# Architecture review — P4-07-chat-graph-integration · engineer revision 1

## Verdict: APPROVED

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | integration code lands in `services/` (turn logic), `schemas/` (wire events), `agents/` (graph), composition in `bootstrap` | `ChatService` in `services/chat.py`; `PlanEvent`/`SourceCitation` in `schemas/chat.py`; `GraphTurnStreamer` in `agents/graph.py`; wiring in `bootstrap.build_chat_service` | None — correct module homes |
| A2 | Layering Router→Service→Agent/Repo | router thin (SSE + authz/rate-limit only); service owns the turn; graph is the agent layer; schemas independent of agents | `api/chat.py` unchanged, no repo/agent imports; service depends on a `GraphTurnRunner` **Protocol** seam (not a hard `GraphTurnStreamer` import); `schemas/chat.py` imports no `agents.*` — `SourceCitation` is a wire DTO the service maps `Citation`→it | None — layering respected end to end; the schema↔agent inversion is correctly avoided via the service-side adapter (`_to_source_citations`) |
| A3 | §3 graph drives the turn | planner → ≥1 worker (when routed) → responder, streamed | `stream_turn` builds one `AgentState`/turn, runs `runner.plan()` (guardrails→recall→planner→workers) then `runner.stream_response()` (real `Responder`); P1 tool-call loop, `ToolRegistry`, `system_prompt`, `max_iterations` removed | None — the walking skeleton is retired as intended |
| A4 | No ReAct parser (locked) | native tool-calling only; no text parser return | tool loop gone; `tool_call`/`tool_result` kept in the union only as an inert wire superset, never emitted; no `output_parser` path | None |
| A5 | LangGraph + typed state (locked) | typed shared `AgentState` through a compiled graph | drives `AgentState` through `GraphTurnStreamer` (compiled `StateGraph`); topology/reducers untouched per non-goals | None |
| A6 | Postgres + Redis only (locked, §4) | Redis session memory; Postgres durable history; guests Redis-only | `RedisSessionMemory` + `RedisCancelRegistry` + `PostgresConversationStore` wired; `_persist_turn`/`_load_prior` no-op for guests (`user_id None`), Postgres rehydration only for logged-in empty-Redis | None — data ownership preserved |
| A7 | In-process embeddings (locked, §6) | `sentence-transformers`, no API cost | `SentenceTransformerEmbeddingClient()` wired as RAG embedder | None |
| A8 | Failover router (locked) | one `LLMRouter` with failover backs planner + responder | single shared `LLMRouter` passed as both `router=` and `responder_router=` | None |
| A9 | SSO-only authz/rate-limit (§7/P3-04) | router-level auth, own-session, rate-limit untouched | `api/chat.py` still `require_auth` + `authorize_session_access` + `rate_limiter.enforce`; `user_id` from token, never body | None |
| A10 | §5.5 message_id | one feedback-ready id/turn, stable across events, stamped on persisted answer | `uuid4().hex` minted once in `stream_turn`, threaded via `AgentState.message_id`, reused for start/plan/done/cancelled, stamped on the persisted assistant `ChatMessage` | None — consistent with the prior message_id ruling |
| A11 | §3 "cite sources" / visible steps | surface which workers ran + citations, additively | new `PlanEvent` (intent/steps/workers) before tokens; `citations` folded onto `DoneEvent`; both additive to `ChatEvent`; existing terminal-event contract intact | None — additive superset; unblocks the paired (F) UI task |
| A12 | Compiled-graph reuse (my P4-06 follow-up #2, part a) | integration owns compiled-once reuse, no per-call compile | `GraphTurnStreamer` compiles `_pre_graph` once at construction; `bootstrap` builds it once/process (cached on `app.state`) | None — this half of the deferred follow-up is satisfied |
| A13 | Post-response tail over the **streamed** answer (my P4-06 follow-up #2, part b) | output-guardrail + memory-writer should run over the real answer, not the discarded placeholder | `plan()` runs the full `_pre_graph` incl. `OUTPUT_GUARDRAIL`/`MEMORY_WRITER` over the deterministic **placeholder** responder; the real streamed answer (`result.content`) never re-enters those nodes | **Design debt (not blocking now).** Both nodes are inert stubs (P10/P9) so zero functional impact today. But the "P9/P10 are pure node-body swaps" promise does NOT hold for these two terminal nodes — see Notes N1. Not forced in this task (YAGNI: no real logic to run yet; the fix is coupled to unspecified P9/P10 design). |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — service is the sole adapter; router and schemas stay clean.
- [x] Honors locked decisions — no ReAct parser; LangGraph typed state; Postgres+Redis only; SSO-only; in-process embeddings; failover router.
- [x] Interfaces-before-implementations — `GraphTurnRunner` Protocol seam decouples the service from LangGraph; `SourceCitation` wire DTO decouples the SSE contract from `agents.state.Citation`.
- [x] Budget posture respected — in-process sentence-transformers, self-hosted, no paid tier.
- [x] Phase fit — satisfies the P4 exit criterion (planner→worker→responder, streams, cites); guardrail/memory stubs flow through unchanged per the task's non-goals.

## Notes

- **N1 (design debt, deferred — must be enforced at P9/P10):** the wired `GraphTurnStreamer._pre_graph`
  includes the post-response tail (`OUTPUT_GUARDRAIL` → `MEMORY_WRITER`), and `plan()` runs that tail over
  the LLM-free **placeholder** responder answer; the service then streams the *real* `Responder` separately,
  so the real answer bypasses both nodes. This exactly reproduces the concern I logged after P4-06 (that the
  chat integration "must drive output guardrail + memory writer over the streamed answer"). I am **not**
  blocking P4-07 on it because: (1) both nodes are inert stubs today — zero functional effect; (2) forcing a
  post-stream tail now is speculative scaffolding around no-op nodes (YAGNI); and (3) the real fix is entangled
  with P9/P10's own designs — notably the inherent tension between an output guardrail that redacts and
  token-by-token SSE (you cannot un-send a streamed token). The **required correction is deferred, not
  waived**: P9 (memory writer) and P10 (output guardrail) are NOT pure node-body swaps — they must restructure
  the post-response path so those nodes run over the actual streamed answer (the service already holds it as
  `result.content` / the persisted assistant message). Any P9/P10 plan that assumes "just swap the node body"
  should be rejected. My memory ruling is updated to reflect that this placeholder-answer tail is now knowingly
  on the `POST /api/chat` path.

- **N2 (accepted):** `PlanEvent.workers` reports the planner-selected set (fan-out runs exactly that set), so
  "selected" == "ran"; a fail-soft worker that errors is still correctly reported as having run. Fine for the
  (F) UI task's needs.

- **N3 (accepted):** terminal-event invariant holds — `_persist_turn` swallows its own exceptions, so a
  post-`done`/post-`cancelled` persistence failure cannot emit a second terminal `error`. Start → exactly one
  of done/cancelled/error.

- **N4 (context):** the all-models-down path now yields a graceful fallback answer + `done` (graph nodes fail
  soft) rather than P1's `error`; the `error` branches are a genuine-infrastructure safety net. This is a
  reasonable behavioral shift and is consistent with §3's fail-soft posture — no design objection.
