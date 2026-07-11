# Code review — P4-03-planner · engineer revision 1

## Verdict: CHANGES_REQUESTED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | major | `app/agents/planner.py:319` | `steps = [s.strip() for s in args.get("steps", []) ...]` iterates `steps` without checking it is a list. If the model returns `steps` as a non-iterable (`null`, a number, a bool — all reachable since the model is untrusted and only `intent`/`args` types are guarded), the list-comp raises `TypeError`. That `TypeError` escapes `_parse_decision` (which only catches `json.JSONDecodeError`) and `plan()` (which only catches `LLMError`), so it propagates out of the planner node and 500s the whole turn. This directly violates the acceptance criterion "malformed tool call → safe default decision, does not raise out of the node" and the function's own docstring ("Returns `None` … never raises"). Verified live: `steps=null/5/true` → `TypeError: 'NoneType'/'int'/'bool' object is not iterable`. | Guard `steps` before iterating (e.g. `raw_steps = args.get("steps", []); if not isinstance(raw_steps, list): raw_steps = []`), or wrap the parse body / the `_parse_decision` call site in a broad `except Exception → return None` so any malformed argument shape falls back. Add a unit test covering non-list `steps` (null / number). |
| C2 | minor | `app/agents/planner.py:276` | `messages.extend(state.history[-_HISTORY_CONTEXT_MESSAGES:])` slices the last 6 history messages at an arbitrary boundary. If that boundary splits an assistant `tool_calls` message from its following `role="tool"` reply, the planner sends an orphan `role="tool"` message to the OpenAI-compatible endpoint → provider 400. It fails soft (400 → `LLMResponseError` (an `LLMError`) → caught → safe default), so it does not crash, but the planner silently degrades to the default decision for every turn whose history window lands on a tool-call boundary. Not wired to the chat endpoint yet, so latent. | When wiring the real `LLMRouter` (or now), restrict the planner's history to text-bearing `user`/`assistant` messages, or make the slice turn-aware, so a split tool-call pair can never be handed to the model. Note carried forward for the chat-endpoint wiring task. |
| C3 | nit | `app/agents/planner.py:319` | Same line: a JSON *string* `steps` (e.g. `"do the thing"`) is not rejected — it is iterated character-by-character, producing single-character "steps" (`['d','o',...]`). Junk plan, no error. | Folded into the C1 `isinstance(..., list)` guard — a non-list `steps` (string included) should fall back to the synthesised default step. |

## Notes
- Verification run in `backend/`: `ruff check app/agents/planner.py app/agents/graph.py` → clean; `mypy app/agents/planner.py app/agents/graph.py` → clean; `pytest tests/test_agent_planner.py -q` → 20 passed. The two pre-existing mypy errors the engineer flagged are outside this task's files.
- The rest of the design is sound and matches the task well: native forced tool-calling (no ReAct parsing) via `PLANNER_TOOL_SCHEMA` + pinned `tool_choice`; LLM-classify / deterministic-route split (`_INTENT_WORKERS` + `_workers_for`) keeps routing conservative and unit-testable; per-intent budgets; `LLMCompleter` Protocol injection keeps the §6.6 cheaper-planner-model option open; graph topology / `route_after_planner` / `PLANNER` node / edge wiring untouched, added only as an additive `build_graph(router=...)` seam.
- Good defensive choices worth keeping: `plan()` catches only `LLMError` (not bare `Exception`), so `asyncio.CancelledError` still cancels the turn on client disconnect; `_parse_decision` already guards `args` and `intent` types and handles empty/whitespace `arguments`. C1 is precisely the one field-type guard that was missed in an otherwise-consistent defensive pattern.
- `_INTENT_WORKERS` intentionally omits `CHAT` (resolved via `needs_grounding` in `_workers_for`) — correct, not a bug.
- Integration tests drive the real compiled graph via `astream`/`ainvoke` and prove only the routed worker executes — exactly what the acceptance criterion asked for.

## Verdict: CHANGES_REQUESTED

---

# Code review — P4-03-planner · engineer revision 2

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | resolved | `app/agents/planner.py:319-321` | Fixed. `raw_steps = args.get("steps", [])` is now type-guarded `if not isinstance(raw_steps, list): raw_steps = []` before the list-comp, and each element is filtered `if isinstance(s, str) and s.strip()`. Non-list `steps` (null / number / bool / object) can no longer raise `TypeError`; the value falls through to the synthesised default step while the (already-validated) `intent` and its routing are preserved. The finer-grained fallback (vs. a blanket `except Exception → return None`) is a good call — it keeps a valid classification instead of discarding it. | — |
| C3 | resolved | `app/agents/planner.py:321` | Fixed by the same `isinstance(raw_steps, list)` guard: a JSON *string* `steps` is no longer a list, so it is rejected and the fallback step is synthesised instead of iterating char-by-char. | — |
| C2 | minor (carried forward) | `app/agents/planner.py` history slice | Unchanged, as the r1 review itself directed ("Note carried forward for the chat-endpoint wiring task"). Still latent-only: the planner is not wired to `POST /api/chat`, `state.history` carries no real `role="tool"` message on any current path, and the failure is already soft (400 → `LLMResponseError` → caught → safe default). Not a gate. | Address when wiring the real `LLMRouter` — make the history slice turn-aware so a split tool-call pair is never sent to the model. |

## Notes
- Verified the fix in place at `app/agents/planner.py` `_parse_decision`: `raw_steps` list-guard + per-element `isinstance(s, str)` filter + `steps or [f"Handle the {intent.value} request."]` fallback. The C1 raise path (`TypeError` escaping `_parse_decision`/`plan()`) is closed.
- New tests confirm the contract: `test_non_list_steps_do_not_raise_and_get_a_fallback` (parametrized over `None, 5, 3.14, True, {"a": 1}` — asserts no raise, correct intent/workers, non-empty steps) and `test_string_steps_are_not_iterated_char_by_char` (asserts `steps == ["Handle the chat request."]`). Both cover exactly the C1/C3 defect.
- Ran `pytest tests/test_agent_planner.py tests/test_agent_graph.py -q` → **37 passed** (was 31 at r1; +6 new). No regressions in the P4-02 graph tests.
- The rest of the r1 assessment stands: native forced tool-calling (no ReAct parsing), LLM-classify / deterministic-route split, per-intent budgets, `LLMCompleter` Protocol injection, graph topology / `route_after_planner` / `PLANNER` node untouched. No new issues introduced by the revision.

## Verdict: APPROVED
