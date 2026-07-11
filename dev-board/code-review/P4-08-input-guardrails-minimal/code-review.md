# Code review — P4-08-input-guardrails-minimal · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | app/guardrails/heuristics.py:54-72 | The coarse deny-list can false-positive on legitimate phrasing like "ignore all previous rejection emails" — pattern 2 (`ignore … all … previous`) matches on the benign `all previous` window even without an attack noun. Acceptable per the documented default-open coarse-net tradeoff, but worth a P10 note. | No change required now. When P10 replaces `screen_input`, add regression cases for benign "ignore/forget all previous <benign-noun>" phrasings so the real classifier doesn't inherit this coarse edge. |
| C2 | nit | app/agents/graph.py:512-517 | The blocked refusal is emitted as a single `StreamChunk` rather than token-by-token. Fine for a canned message, but the SSE client sees one large `token` event for a block vs. incremental tokens for a normal turn. | Optional: none — canned refusal as one chunk is a reasonable choice; noting only for UI consistency awareness. |

## Notes
- **Acceptance criteria all met and verified locally:**
  - Blocked turn short-circuits *before* planner/workers/responder — confirmed by `test_blocked_turn_routes_straight_to_terminal_tail` (node order = `[input_guardrail, output_guardrail, memory_writer]`) and by spies in `test_blocked_turn_never_calls_planner_or_responder_llm` (planner + responder router `complete`/`stream` never called). The conditional edge `INPUT_GUARDRAIL → {MEMORY_RECALL | OUTPUT_GUARDRAIL}` is the only topology change; the allowed path is byte-for-byte the P4-02 sequence.
  - `input_safety` carries a real verdict: `allowed=False` + non-empty `categories` + a `reason` on block, `allowed=True`/empty on legit turns.
  - Blocked turn yields a well-formed terminal `done` (not an exception, not `error`, no `plan` event) with the generic `REFUSAL_MESSAGE`; the flagged content ("system prompt") is not echoed and the internal deny-list/categories are never surfaced — verified end-to-end through `ChatService` and `POST /api/chat`.
- **Security posture is sound for this slice:** `screen_input` is pure regex over `user_message` — no LLM/network/eval, no untrusted input reaching a tool, refusal is a module constant (no user content interpolated into the SSE stream), no secrets. No SSRF/injection surface introduced.
- **DRY/SoC honored:** length/emptiness left to `ChatRequest` schema; heuristic isolated in `app/guardrails/heuristics.py` behind a stable `SafetyVerdict` contract so P10 swaps detection without touching graph wiring; `AgentState`/reducers and planner/worker/responder bodies untouched per constraints.
- **Streaming vs. buffered paths both handled:** the guardrail node stamps `response`/`finish_reason`/`message_id` for the buffered `run_graph` path, and `GraphTurnStreamer.stream_response` short-circuits on `input_safety.allowed is False` for the streamed path — one source of truth for the refusal text. `ChatService` correctly needs no change (blocked turn = `plan is None` → no `PlanEvent`, normal token→done loop).
- **Verification I re-ran (not just trusting the report):** `ruff check` on changed files → clean; `mypy app/guardrails app/agents/graph.py` → clean; `pytest tests/test_input_guardrails.py` → 22 passed; `pytest tests/test_agent_graph.py tests/test_chat_service.py tests/test_chat_api.py` → 21 passed. No regression in the adjacent suites.
- Both findings are nit-level and non-gating; C1 is a forward-looking note for P10, not a defect in this minimal slice.
