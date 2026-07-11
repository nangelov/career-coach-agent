# Engineer report — P4-07-chat-graph-integration · Revision 1

## Summary
`POST /api/chat` now drives each turn through the compiled multi-agent LangGraph
(`app/agents/graph.py`) instead of P1's raw LLM-router + tool-registry loop. `ChatService`
was rebuilt to construct an `AgentState` per turn, run the pre-responder pipeline
(guardrails → recall → planner → workers), surface a new `plan` SSE event (which workers ran),
stream the real `Responder`'s tokens, and emit `done` carrying the answer's `citations`. All the
cross-cutting concerns the graph does **not** own — Redis session memory, durable Postgres
persistence, and Redis-backed cancel/stop — are preserved unchanged in the service layer.

The scope fit in one reviewable change. It was larger than a typical task mainly in **test
adaptation** (7 suites construct `ChatService`); every existing contract (SSE ordering, cancel,
persistence, rehydration, message_id stability) was ported to the graph mechanism rather than
dropped.

## Files changed
- `app/schemas/chat.py` — added `PlanEvent` (intent/steps/workers, emitted before tokens) and
  `SourceCitation` (wire DTO); added `citations` to `DoneEvent`; added `PlanEvent` to the
  `ChatEvent` union. `tool_call`/`tool_result` retained in the union (wire superset) but no
  longer emitted. Updated the vocabulary docstring.
- `app/agents/graph.py` — added `GraphTurnStreamer`: the compiled-**once**, reusable runner
  (`plan()` runs the pre-responder graph; `stream_response()` streams the real `Responder`;
  `aclose()` releases the router). Refactored the free `stream_graph` to delegate to it (DRY);
  its documented yield contract (tokens… then one terminal `AgentState`) is unchanged.
- `app/agents/__init__.py` — export `GraphTurnStreamer`.
- `app/services/chat.py` — rewritten as graph-driven. Defines the `GraphTurnRunner` Protocol
  (the seam the service depends on), builds `AgentState` per turn, emits `start`→`plan`→`token`…
  →`done`, polls cancel at three checkpoints (before the graph run, before the token stream,
  every N chunks during streaming), and maps `AgentState.citations` → wire `SourceCitation`.
  Removed the tool-call loop, `ToolRegistry`, `system_prompt`, and `max_iterations`.
- `app/bootstrap.py` — `build_chat_service` now wires a `GraphTurnStreamer` (the shared
  `LLMRouter` as both planner `router=` and `responder_router=`, the in-process
  `SentenceTransformerEmbeddingClient` and shared Postgres pool for the RAG worker). Dropped the
  now-unused tool-registry wiring.
- `tests/fakes.py` — added `FakeGraphRunner` (scripted `GraphTurnRunner` double, same
  `scripts`/`always` shape as `FakeRouter`).
- `tests/test_chat_service.py` — rewritten for the graph service (plain answer + streaming,
  history replay, `plan` event, worker-turn citations, terminal-error safety net).
- `tests/test_chat_cancel.py`, `tests/test_chat_persistence.py`, `tests/test_message_id.py`,
  `tests/test_session_memory.py`, `tests/test_p2_exit_verification.py` — adapted to
  `FakeGraphRunner`; `router.calls` provider-payload assertions became `runner.plan_states[i]`
  (history slice + `user_message`) assertions, preserving each contract.
- `tests/test_chat_api.py` — added an end-to-end test through the **real** `POST /api/chat` +
  real `GraphTurnStreamer` (fake responder-router/planner/embedder/DB) proving a worker-routed
  turn streams tokens **and** returns citations.

## Key decisions
- **Two-phase runner (`plan` / `stream_response`) rather than one `stream()`** (design §3
  "visible thinking/tool steps", "stream early"). The pre-responder graph completes before token
  streaming, so splitting the seam lets the service (a) emit the `plan` event *before* tokens and
  (b) keep a cancel checkpoint between planning and responding — a multi-agent turn is more
  latent than a single completion. `stream_graph`'s free-function contract is unchanged; it now
  delegates to `GraphTurnStreamer` (DRY, and it delivers the "compiled-graph reuse" that
  function's docstring deferred to this task).
- **`plan` event + citations-on-`done`, additive to the `ChatEvent` union** (task's "extend
  additively"). `plan.workers` tells the client which workers ran (fan-out runs exactly the
  selected set); citations fold into `done` since sources are only complete once the answer is.
  Kept `tool_call`/`tool_result` in the union so the wire stays a superset of P1-08's frontend.
- **Schema layer stays independent of the agent layer**: `SourceCitation` is a wire DTO in
  `schemas/chat.py`; the service maps `AgentState.Citation` → it. No `agents` import in `schemas`
  (avoids inverting Router→Service→Agent layering).
- **All-models-down now yields a graceful fallback answer + `done`, not an `error` event.** The
  P4 graph nodes (planner/workers/responder) fail soft by design (P4-03/04/05/06), so the
  service's `error` branches are a safety net for genuine infrastructure failures. This is a
  deliberate behavioral change from P1; `test_chat_service.py` was updated accordingly (the
  synthetic `plan_error` path still exercises the terminal-`error` safety net).

## How to verify
- `cd backend && make lint && make typecheck && make test` (or the `uv run --no-sync` commands).
- End-to-end: `tests/test_chat_api.py::test_worker_routed_turn_streams_tokens_and_cites_end_to_end`
  drives the real graph through the HTTP endpoint and asserts `event: plan`, `event: token`, and
  a `done` citation (`rag-source`) in the SSE body — no live HF/Postgres.

## Tests (final step — mandatory)
- `uv run --no-sync ruff check .` → **All checks passed!**
- `uv run --no-sync ruff format --check` (all files I touched) → **13 files already formatted**.
- `uv run --no-sync mypy app/ tests/` → **1 error, pre-existing and not mine**:
  `tests/test_llm_router.py:309: Unused "type: ignore" comment`. Confirmed pre-existing by
  `git stash` (the error persists with all my changes stashed; `test_llm_router.py` is an
  untouched, committed file). It is a `# type: ignore[override]` that the local mypy version
  flags as unused but CI's version needs — removing it would risk breaking CI, so it is left as
  found and flagged here rather than silently touched outside this task's scope.
- `uv run --no-sync pytest -q` → **286 passed, 43 skipped** (skips are live-Postgres/integration
  suites that gate on DB reachability). No failures.

## Self-check
- [x] Meets acceptance criteria — turns run through `stream_graph`/`GraphTurnStreamer` (planner →
  ≥1 worker when routed → responder); `plan` + `done.citations` surface workers-ran + sources;
  token streaming preserved; cancel works against a graph turn; session memory + durable
  persistence unchanged; router-level authz/rate-limit untouched; end-to-end worker-turn test
  proves tokens + non-empty citations through the real endpoint with injected fakes.
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (schemas independent of
  agents; service is the only adapter; router unchanged).
- [x] Tests/lints pass (results above); the one mypy line is pre-existing and documented.

## Notes on scope preserved (non-goals honored)
- No changes to `AgentState`, graph topology, or P4-01 reducers.
- Guardrail (P10) and memory-recall/learn (P9) stub node bodies flow through unchanged.
- Router-level authz/rate-limit (P3-04) and the SSE framing in `api/chat.py` are untouched
  (`ChatEvent` extension is additive, no router change needed).
