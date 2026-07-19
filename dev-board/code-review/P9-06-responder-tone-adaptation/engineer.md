# Engineer report — P9-06-responder-tone-adaptation · Revision 1

## Summary
The Response Agent now consumes `state.memory` (populated by P9-02) to adapt tone/depth/style.
`Responder._build_messages` injects a single **trusted persona** system turn built from the
recalled explicit `preferences` and inferred `memories` when either is non-empty, framing
explicit preferences as authoritative-and-overriding per §5.4 point 4. When recall found nothing
(guest / nothing learned) the prompt is byte-for-byte the pre-P9-06 assembly. Prompt-assembly
only — no new LLM call; both `synthesize()` and `stream()` share `_build_messages`, so one change
point covers both paths.

## Files changed
- `backend/app/agents/responder.py` — added `_PERSONALIZATION_PREAMBLE`, `_personalization_note`,
  `_preference_lines`, `_render_pref_value`; `_build_messages` now injects the personalization
  turn between the persona and the job-hunting redirect note. `Mapping` added to imports.
- `backend/tests/test_agent_responder.py` — 5 new tests (no-memory baseline-identical, prefs-only,
  memories-only, both-with-precedence-framing, streaming path).

## Key decisions
- **Trusted, not fenced.** Per task note + §5.4, prefs/memories are first-party, user-controlled,
  PII-gated (P9-04) data — injected as plain persona context, not through `fence_untrusted` (which
  is reserved for untrusted worker/crawled grounding). Placed adjacent to the persona prompt.
- **Explicit precedence made textual, not implied.** The preferences line is labelled
  "authoritative … the explicit preference wins"; the memories line "inferred — lower priority".
  This satisfies the "distinguishable framing" criterion so precedence exists at generation time
  (complementing P9-05's CRUD-level override), and the explicit block is ordered before inferred.
- **Empty ⇒ no block.** Guards on `_preference_lines` + non-blank memories both empty → returns
  `None` → prompt unchanged, mirroring the planner's `_memory_note` idiom (DRY with existing code).
- **Permissive value rendering.** `preferences` is user-controlled JSONB; `_render_pref_value`
  flattens str/bool/number/list/nested-map and drops empty values so a partial prefs object never
  injects noise (KISS — no schema assumptions beyond the §5.4 shape).

## How to verify
- `cd backend && source .venv/bin/activate`
- `python -m pytest tests/test_agent_responder.py -q`

## Tests (final step — mandatory)
- `pytest tests/test_agent_responder.py -q` → **18 passed** (13 existing + 5 new).
- `ruff check app/agents/responder.py tests/test_agent_responder.py` → **All checks passed**.
- `mypy app/agents/responder.py` → **Success: no issues found**.
- Full suite `pytest -q` → **837 passed, 72 skipped** (11.85s). No failures; no fixes needed.

## Self-check
- [x] Meets acceptance criteria (injects block when non-empty; both signals represented w/ explicit
  precedence; empty ⇒ unchanged prompt; both `synthesize` + `stream` covered by tests; distinguishable
  explicit-vs-inferred framing test present).
- [x] No secrets; layering respected (Agent-node prompt-assembly change only; no recall/learn/CRUD
  change, no new LLM call, no frontend change).
- [x] Tests/lints/types pass (pasted above).
