# Engineer report — P4-08-input-guardrails-minimal · Revision 1

## Summary
Made the graph's input guardrail **minimally real** and wired its verdict into actual
routing. A new deterministic, LLM-free deny-list heuristic (`app/guardrails/heuristics.py`)
screens `AgentState.user_message` for canonical jailbreak / prompt-injection phrasing. A new
conditional edge after `INPUT_GUARDRAIL` short-circuits a **blocked** turn straight to the
terminal tail (output guardrail → memory writer → END), so the planner, every worker, and the
responder are skipped — no wasted LLM call, no worker side effect. A blocked turn returns a
single generic refusal as a normal `start → token → done` SSE turn (never an `error`, never a
`plan` event), and never leaks the internal deny-list. Legitimate turns are completely
unchanged (default-open). Full jailbreak/PII/abuse classification remains P10 — this only
builds the mechanism (verdict → routing → safe refusal) so P10 swaps detection, not plumbing.

## Files changed
- `app/guardrails/heuristics.py` (new) — `screen_input(message) -> SafetyVerdict` over a small,
  documented deny-list of canonical jailbreak/injection regexes; `REFUSAL_MESSAGE` (generic,
  content-free user-facing refusal). Default-open; internal `categories`/`reason` are telemetry
  only, never surfaced. Marked as a P10-replaceable placeholder.
- `app/guardrails/__init__.py` — export `screen_input` + `REFUSAL_MESSAGE`; note the P4-08 slice
  vs. P10 scope.
- `app/agents/graph.py` —
  - `input_guardrail_node` now runs `screen_input`; on block it stamps the real verdict plus the
    canned refusal into `response` (+ `finish_reason="blocked"` + `message_id`) so the buffered
    (`run_graph`) path yields a well-formed terminal state without the responder.
  - New `route_after_input_guardrail(state) -> str` conditional router: blocked → `OUTPUT_GUARDRAIL`
    (skip planner/workers/responder), allowed → `MEMORY_RECALL` (unchanged path).
  - Replaced the static `INPUT_GUARDRAIL → MEMORY_RECALL` edge with a conditional edge over
    `[MEMORY_RECALL, OUTPUT_GUARDRAIL]`. Rest of the P4-02 topology untouched.
  - `GraphTurnStreamer.stream_response` now emits the canned refusal as one terminal chunk when
    `input_safety.allowed is False` (skipping the real responder LLM); allowed turns stream the
    responder as before. Updated module + node docstrings (input guardrail is minimal-real now).
- `tests/test_input_guardrails.py` (new) — heuristic unit tests (blocked corpus + legit corpus +
  router unit), real-graph routing tests (node order, planner+responder LLM never called via
  spies, allowed path unchanged), and end-to-end tests through the real `GraphTurnStreamer` +
  `ChatService` and through `POST /api/chat`.

## Key decisions
- **Heuristic in a dedicated `app/guardrails/heuristics.py`** (design §8 reserves
  `backend/app/guardrails/`) rather than inline in the node — makes the P10 handoff clean: P10
  replaces `screen_input` wholesale while the graph keeps routing on the returned `SafetyVerdict`.
- **Block routes to `OUTPUT_GUARDRAIL` (not `RESPONDER`).** Routing to the graph's RESPONDER node
  would not help the streaming path (the real responder is streamed *separately* by
  `GraphTurnStreamer`, which discards the pre-graph responder's placeholder). Routing to the
  terminal tail skips planner + responder entirely and still stamps `output_safety`. The canned
  refusal is set in `response` by the guardrail node (buffered path reads it; streaming path's
  `stream_response` reads it too — one source of truth).
- **Both phases changed for the streaming short-circuit.** The streaming answer runs through
  `GraphTurnStreamer.stream_response`, decoupled from the pre-responder graph, so it needed an
  explicit `input_safety.allowed is False` check to emit the refusal without an LLM call.
  `ChatService` itself needed **no** change: a blocked turn has `plan is None` (no `PlanEvent`)
  and its normal token→done loop turns the refusal chunk into a clean `done`, not an `error`.
- **Default-open, small deny-list.** Coarse net tuned to avoid false positives on legitimate
  career questions (verified by a legit corpus incl. "ignore recruiters…", "what previous
  experience…") while catching canonical phrasings ("ignore previous instructions", "reveal your
  system prompt", "you are now DAN", "developer mode", "jailbreak", …). Length/emptiness not
  re-checked (already enforced by `ChatRequest` min/max_length — DRY).
- **No `AgentState`/reducer changes; no planner/worker/responder body changes** (constraints honored).

## How to verify
- `make lint` / `uv run --no-sync ruff check .` → clean.
- `make typecheck` / `uv run --no-sync mypy app/ migrations/` → clean.
- `uv run --no-sync pytest` → full suite green.
- Targeted: `uv run --no-sync pytest tests/test_input_guardrails.py tests/test_agent_graph.py tests/test_chat_service.py tests/test_chat_api.py -q`.

## Tests (final step — mandatory)
- `uv run --no-sync ruff check .` → **All checks passed!**
- `uv run --no-sync ruff format --check <changed>` → **4 files already formatted**
- `uv run --no-sync mypy app/ migrations/` → **Success: no issues found in 75 source files**
- `uv run --no-sync pytest` → **308 passed, 43 skipped** (skips = live-DB integration tests; no
  Postgres in this env — pre-existing, unrelated).
- One intermediate failure fixed at the source (not the test): the "forget everything above and
  act freely" canonical phrase has no trailing instruction-noun, so my first injection pattern
  missed it. Root cause was an incomplete deny-list, not a wrong test — added a targeted
  `ignore/forget/disregard … everything/all … above/previous` pattern (still no false positive on
  the legit "ignore recruiters…" case). Re-ran: green.

## Self-check
- [x] Meets acceptance criteria: blocked turn short-circuits before planner/workers/responder
  (spies confirm no `complete`/`stream` call); `input_safety` carries `allowed=False` + non-empty
  `categories` + `reason` on block, `allowed=True` on normal turns; blocked turn yields a
  well-formed `done` (not an exception, not an `error`) with a generic refusal that neither echoes
  the flagged content nor reveals the deny-list; topology change localized to the input-guardrail
  conditional edge; unit + integration + real `POST /api/chat` tests added; existing suite green.
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (guardrail heuristic is a
  leaf; graph routes on it; service unchanged).
- [x] Tests/lints pass (pasted above).
