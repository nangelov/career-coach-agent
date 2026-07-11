# Engineer report — P4-03-planner · Revision 2

## Summary
Replaced the P4-02 hardcoded `planner_node` stub with a real, LLM-backed planner. New
`app/agents/planner.py` classifies the turn's intent via **native tool-calling** (no ReAct
parsing), decomposes it into steps, derives a **conservative, deterministic** worker
routing from the intent, and sets a per-intent iteration budget — packaged as a
`PlannerDecision` the existing graph fans out on. The graph topology, `route_after_planner`
contract, `PLANNER` node name and `add_conditional_edges` wiring are unchanged; only the
node that produces the decision changed, plus an additive `router=` seam on `build_graph`.

## Files changed
- `app/agents/planner.py` (new) — `Planner` node + `LLMCompleter` protocol, the
  `record_plan` tool schema/prompt, intent→worker mapping, budget defaults, fail-soft
  parsing.
- `app/agents/graph.py` — imports `Planner`/`LLMCompleter`; `build_graph` gains a `router=`
  parameter that wires the real `Planner`; default `planner_node` is now a dependency-free
  no-router safe fallback (route straight to responder); `[STUB → P4-03]` marker removed
  and the module docstring updated.
- `app/agents/__init__.py` — export `Planner`, `LLMCompleter`, `PLANNER_TOOL_NAME`,
  `PLANNER_TOOL_SCHEMA`.
- `tests/test_agent_planner.py` (new) — unit tests (routing, steps, budget, tool-call
  contract, failure paths) + real-graph integration tests proving the decision drives the
  fan-out.

## Key decisions
- **Native tool-calling, forced function** (CLAUDE.md §6 item 2, task "Implementation
  approach"). The planner passes one JSON-schema tool (`PLANNER_TOOL_SCHEMA`, same shape as
  `app/tools/` P1-03) and pins `tool_choice` to it, then parses
  `ToolCall.function.arguments`. No free-text/ReAct parsing.
- **Classification (LLM) vs. routing (deterministic) split.** The LLM assigns exactly one
  `Intent` and writes steps; worker routing is derived from the intent via `_INTENT_WORKERS`
  (`job_search→[JOB_SEARCH]`, `pdp→[PDP_RESUME]`, `cv_question→[RAG]`, `smalltalk→[]`).
  This keeps routing conservative and unit-testable (design §3) rather than trusting the
  model to emit node names while the real workers are still stubs (P4-04..P4-06).
- **`cv_question → [RAG]`** (not `[RAG, PDP_RESUME]`): CV questions are answered by
  retrieval; PDP building is a separate `pdp` intent. Documented in-module.
- **`chat` grounding is the one model judgement call**: schema carries a `needs_grounding`
  flag; `chat`+grounding→`[RAG]`, else `[]` (design §3 "chat may or may not need grounding").
- **Injected dependency, not a hand-rolled client** (task note; design §6.6). `Planner`
  takes an `LLMCompleter` (structurally the P1-02 `LLMRouter`) so pointing the planner at a
  cheaper/faster model tier later is a wiring change. Defined as a narrow `Protocol` so the
  planner imports no `openai`/router internals.
- **Per-intent budget** (design §3 "sets a budget"): `smalltalk=1`, `chat`/`cv_question=3`,
  `job_search`/`pdp=5`; `token_budget` left `None` (provider default; optional per task).
- **Fail-soft** (task acceptance): router error, missing tool call, non-JSON / non-object
  arguments, or unknown intent → safe default (`CHAT`, no workers → responder). The node
  never raises out of the graph.
- **`build_graph(router=...)` added, `planner=` seam kept.** Resolution order:
  explicit `planner` node (test seam) → `router` (real `Planner`) → dependency-free
  `planner_node` default (so the import-time module `graph` stays side-effect-free until the
  chat endpoint injects a router, which is out of scope here).
- **`Planner` is an async node** (it does LLM I/O). The production entrypoint `run_graph`
  already uses `ainvoke`; integration tests use `astream`/`ainvoke` accordingly.

## How to verify
```
cd backend && source .venv/bin/activate
ruff check .
mypy app/agents/planner.py app/agents/graph.py
python -m pytest tests/test_agent_planner.py tests/test_agent_graph.py -q
python -m pytest -q          # full suite
```

## Tests (final step — mandatory)
- `ruff check .` → **All checks passed!**
- `mypy app/agents/planner.py app/agents/graph.py` → **Success: no issues found in 2 source
  files**. `mypy app tests` reports only **2 pre-existing** errors in files I did not touch
  (`tests/test_message_id.py:71`, `tests/test_llm_router.py:309`) — confirmed present on
  HEAD with my changes stashed; not in scope.
- `python -m pytest tests/test_agent_planner.py tests/test_agent_graph.py -q` → **31 passed**.
- `python -m pytest -q` (full suite) → **240 passed, 43 skipped** (skips are env-gated
  heavy-dep tests). No failures.
- One failure was hit and fixed during development: the integration tests initially drove
  the graph with the **sync** `compiled.stream`/`invoke`, which raises
  `TypeError: No synchronous function provided to "planner"` because `Planner` is an async
  node. Root cause was the test using the wrong runtime API (not an implementation bug);
  fixed by switching those tests to `astream`/`ainvoke` (the same async path `run_graph`
  uses in production).

## Self-check
- [x] Meets acceptance criteria — `planner.py` produces a full `PlannerDecision`; graph
  wired via `router=`; intent→worker mapping tested; budget populated; failure path safe;
  unit + real-graph integration tests present; ruff/mypy clean; P4-02 tests still green.
- [x] No secrets committed; Router→Service→Agent layering respected (planner depends on the
  `LLMCompleter`/`LLMRouter` surface, never a DB driver or the provider SDK).
- [x] Tests/lints pass (pasted above).
- [x] Graph topology / `route_after_planner` / `PLANNER` node / conditional-edge wiring
  unchanged; `AgentState` and reducers untouched; not wired into `POST /api/chat`.

## Response to review (revision 2)

### code-review.md — CHANGES_REQUESTED

- **C1 (major) — non-list `steps` raises `TypeError` out of the node.** Fixed in
  `_parse_decision` (`app/agents/planner.py`). Before iterating, `steps` is now
  type-guarded: `raw_steps = args.get("steps", []); if not isinstance(raw_steps, list): raw_steps = []`.
  A `null` / number / bool / object `steps` value now falls through to the synthesised
  default step (`f"Handle the {intent.value} request."`) instead of raising, honouring the
  "malformed tool call → safe default, never raises" contract. Note the fail-soft here is
  *finer-grained* than a blanket fallback: the model-supplied `intent` is already validated
  (`Intent(...)`), so a bad `steps` field keeps the good intent/routing and only replaces
  the junk steps — a broad `except Exception → return None` would have thrown away a valid
  classification. Added `test_non_list_steps_do_not_raise_and_get_a_fallback`
  (parametrized over `None`, `5`, `3.14`, `True`, `{"a": 1}`) proving no raise + correct
  intent/workers + non-empty steps.

- **C3 (nit) — JSON-string `steps` iterated char-by-char.** Folded into the C1
  `isinstance(..., list)` guard: a string is no longer a `list`, so it is rejected and the
  fallback step is synthesised (no more `['d','o',...]`). Added
  `test_string_steps_are_not_iterated_char_by_char` asserting `steps == ["Handle the chat request."]`.

- **C2 (minor, latent/carry-forward) — history-slice tool-call boundary.** Left as-is per
  the review's own guidance ("Note carried forward for the chat-endpoint wiring task").
  The planner is not yet wired to `POST /api/chat`, `state.history` is never populated with
  a real `role="tool"` message on any current path, and the failure is already soft (400 →
  `LLMResponseError` → caught → safe default). Fixing it correctly requires turn-aware
  slicing that belongs with the real `LLMRouter` wiring; doing it now would be speculative
  (YAGNI) against a history shape that does not yet exist. Carried forward to the
  chat-endpoint task.

### architecture-review.md — APPROVED

- Non-blocking `max_iterations` inconsistency (dependency-free `graph.planner_node` default
  uses `PlannerDecision`'s field default `5`; `planner._safe_default_decision()` uses
  `_INTENT_MAX_ITERATIONS[Intent.CHAT] == 3`): left as noted — both are safe, the
  divergence is cosmetic, and the architect explicitly scoped alignment to "when the chat
  endpoint injects the real router" (the no-router `planner_node` becomes import-time-only
  scaffolding then). Not touched to keep this revision focused on the C1 blocker.

### Tests (final step — mandatory, revision 2)
- `ruff check app/agents/planner.py tests/test_agent_planner.py` → **All checks passed!**
- `mypy app/agents/planner.py app/agents/graph.py` → **Success: no issues found in 2 source
  files**.
- `python -m pytest tests/test_agent_planner.py tests/test_agent_graph.py -q` → **37 passed**
  (was 31; +6 new: 5 parametrized non-list cases + 1 string case).
- `python -m pytest -q` (full suite) → **246 passed, 43 skipped**. No failures.
