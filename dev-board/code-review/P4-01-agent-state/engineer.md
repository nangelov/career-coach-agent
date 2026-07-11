# Engineer report — P4-01-agent-state · Revision 1

## Summary
Implemented the typed shared LangGraph state object (`agents/state.py`) that is threaded
through every node of the P4 multi-agent graph (recall → planner → workers → responder →
guardrails → memory-writer), per design §3. This is a **state-only** task: no graph
wiring, no planner/worker/responder nodes (those are separate P4 tasks that consume this
object). Guardrail (P10) and memory-recall (P9) fields are reserved now so those phases
have a home without reshaping state later.

A prior interrupted run had drafted `state.py`, the `__init__.py` exports, and the test
module. I reviewed all three critically against the acceptance criteria, verified every
reused type against the current codebase, and found the design sound. The only concrete
defect was a formatting violation in the test file (a line over the 100-char limit that
`ruff format` rejected). I fixed that, then confirmed the whole suite is green.

## Files changed
- `backend/app/agents/state.py` (new) — the `AgentState` Pydantic model + supporting
  sub-models (`PlannerDecision`, `WorkerResult`, `Citation`, `SafetyVerdict`,
  `MemoryContext`), enums (`Intent`, `WorkerName`, `GuardrailStage`), and the
  `merge_worker_results` reducer.
- `backend/app/agents/__init__.py` (modified) — public exports of the state API.
- `backend/tests/test_agent_state.py` (new) — 11 unit tests; reformatted to satisfy
  `ruff format`.

## Key decisions
- **Pydantic `BaseModel`, not bare `TypedDict`** (design §3 explicitly says "typed object
  (Pydantic)"). LangGraph's `StateGraph` accepts a `BaseModel` schema and honours per-field
  reducers declared via `typing.Annotated` metadata exactly as it does for `TypedDict`.
  Pydantic additionally buys validation, enum coercion, and a first-class
  `model_dump_json` / `model_validate_json` round trip — load-bearing because the state
  crosses the Redis/Celery boundary (memory-writer is async, §3).
- **Parallel-worker reducer semantics** (the task's flagged main technical risk):
  - `worker_results: Annotated[dict[str, WorkerResult], merge_worker_results]` — each
    worker writes under its **own** `WorkerName` key, so a right-biased key-wise dict
    merge lets concurrent workers accumulate without clobbering.
  - `citations: Annotated[list[Citation], operator.add]` — list concatenation so every
    worker's grounding sources add up.
  - Single-writer fields (`plan`, `response`, `finish_reason`, `input_safety`,
    `output_safety`) intentionally carry **no** reducer — last-write-wins, only one node
    writes each. This is verified by a real `StateGraph` fan-out test, not just bare
    function calls.
- **Reuses existing vocabulary — no parallel copies** (acceptance criterion):
  - identity `role: SessionRole` from `app.schemas.auth` (the `Literal["guest","user"]`
    already used by the token codec/session store); `session_id`/`user_id` bounds
    (`max_length=64`) mirror `SessionRecord` and the `String(64)` columns from P2.
  - `history: list[ChatMessage]` from `app.llm.types` — the LLM-ready message shape
    (renders via `to_openai`), which is exactly "a message history slice usable as LLM
    input" (§3).
  - `message_id` reuses the P1/§5.5 feedback-id convention verbatim
    (`ChatMessage.message_id`) rather than inventing a new id.
- **Guardrails default-open** (`SafetyVerdict.allowed = True`) so an un-run guardrail does
  not block the pipeline before P10 fills it in; shape exists now for both P4's minimal
  hook and P10's full classifier.

## How to verify
```bash
cd backend
uv run --no-sync ruff check app/agents/ tests/test_agent_state.py
uv run --no-sync ruff format --check app/agents/ tests/test_agent_state.py
uv run --no-sync mypy app/agents/ tests/test_agent_state.py
uv run --no-sync pytest tests/test_agent_state.py -q
# full suite (docker db+redis up):
make test-integration
```

## Tests (final step — mandatory)
- `ruff check .` → **All checks passed!**
- `ruff format --check .` → my two files clean. (3 **pre-existing** files flagged —
  `app/repositories/models/identity.py`, `tests/test_feedback_reader.py`,
  `tests/test_p3_exit_verification.py` — all committed in P3, untouched by this task, out
  of scope. Left as-is rather than expanding scope.)
- `mypy app/ migrations/` → **Success: no issues found in 69 source files** (+ test file
  clean).
- `make test-integration` (full suite, live docker Postgres+Redis) → **252 passed in
  6.03s**, including the 11 new `test_agent_state.py` cases.
- The only failure encountered was the test-file format violation (a `WorkerResult(...)`
  call under the 100-char line limit). Root cause: test bug (formatting), not implementation.
  Fixed with `ruff format`; re-ran to green.

## Self-check
- [x] Meets acceptance criteria — identity, history slice, planner decisions
  (intent/steps/workers/iteration+token budget), per-worker results (keyed, reducer-merged),
  citations (concatenated), input+output safety verdicts, memory-recall slot, `message_id`
  bookkeeping; reducer semantics proven under a real `StateGraph` fan-out; reuses P1/P2/P3
  types; JSON round-trip + validation tests present.
- [x] No secrets committed; module is a pure state/vocabulary layer (no DB drivers, no
  services) — respects Router→Service→Agent/Repo layering.
- [x] Tests/lints pass (results pasted above).
