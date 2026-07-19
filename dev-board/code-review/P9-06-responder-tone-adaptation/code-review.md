# Code review — P9-06-responder-tone-adaptation · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/app/agents/responder.py:307 & backend/app/agents/planner.py:313 | The `[m for m in state.memory.memories if isinstance(m, str) and m.strip()]` filter is duplicated verbatim between the planner's `_memory_note` and the responder's `_personalization_note` (mild DRY). | Optional: lift to a small `MemoryContext.clean_memories()` helper. Non-blocking — the two live in different modules with different framing. |
| C2 | nit | backend/app/agents/responder.py:295-326 | `preferences`/`memories` are injected as an unfenced system turn. This is the task-mandated "trusted first-party" treatment, and any injection is self-scoped (a user manipulating their own responder — no cross-user/privilege boundary crossed), so it is not a security gate. Noted only so it is on record that the P9-04 gate is a PII gate, not an injection gate. | None — documented, accepted per task note + §5.4. |

## Notes
- All acceptance criteria met and covered by tests:
  - **Empty recall ⇒ prompt unchanged** — `test_no_memory_prompt_is_unchanged_from_baseline` asserts byte-equality between a default `MemoryContext` state and a no-memory state, plus absence of the block markers (true no-regression guard).
  - **Both signals represented + explicit precedence** — `_personalization_note` labels `preferences` "authoritative … the explicit preference wins" and `memories` "inferred — lower priority", ordered explicit-before-inferred; `test_both_prefs_and_memories_with_explicit_precedence_framing` asserts the distinguishable wording *and* the ordering, so §5.4 point 4 is stated at generation time, not left to the model.
  - **Both paths** — single `_build_messages` change point; `synthesize()` and `stream()` both exercised (`test_personalization_applies_on_the_streaming_path`).
  - Prefs-only / memories-only cases each assert the *other* block is absent — good negative coverage.
- Correctness: `state.memory` is a Pydantic field with `default_factory=MemoryContext`, so never `None`; guards on empty prefs/blank memories return `None` cleanly. `_render_pref_value` handles scalars/bool/list/nested-Mapping and drops empties (permissive over user-controlled JSONB, no schema assumption) — recursion is bounded by acyclic JSON, no cycle risk. Placement (persona → personalization → job-hunting redirect → grounding → history → turn) is coherent.
- Fail-soft posture, citation pass-through, and the untrusted `_grounding_block` fencing are untouched by this change — no regression to prior behaviour.
- Verified locally: `pytest tests/test_agent_responder.py -q` → 18 passed; `ruff` clean; `mypy app/agents/responder.py` clean. Change is scoped to `responder.py` + its test (other P9 files in the working tree belong to sibling tasks and were out of scope).
