# Task P10-03-output-guardrails — complete output guardrails (system-prompt leakage + injection echo)

- **Phase:** P10   **Status:** ENG   **Tags:** (B)

## Scope
Design §7 / §7.3 requires **output guardrails**: "block system-prompt leakage, refuse
policy-violating content, strip injected instructions echoed from untrusted content."

`app/guardrails/heuristics.py::screen_output` today only strips the same small canonical
deny-list phrasings as the input side (echoed injection). This task completes the output side:

1. **System-prompt leakage.** Add detection for the model echoing back its own system
   prompt / internal instructions / tool definitions verbatim or near-verbatim in the final
   answer (e.g. it was coaxed into repeating configuration text). Block or redact — decide and
   document which (redaction is consistent with the existing `screen_output` posture: "a scrub
   neutralises rather than blocks: the answer is still returned, just cleaned").
2. **Strip injected instructions echoed from untrusted content** — this exists for the small
   canonical deny-list (P4-08); extend it to work with whatever new classifier P10-01 introduces
   if it produces a reusable *output*-side signal (e.g. if the injection classifier can also score
   the assistant's own text, wire it in here rather than keeping two disconnected mechanisms).
   If P10-01 lands first, read its `engineer.md` to see what's reusable.
3. Keep the `OutputScreenResult` contract (`text`, `verdict`, `modified`) — this is what
   `app.agents.responder` (or wherever `screen_output` is invoked) consumes.

## Acceptance criteria
- [ ] `screen_output` (or its replacement, same contract) detects and redacts verbatim/near-verbatim
      system-prompt leakage in the final answer.
- [ ] Injected-instruction echoing from untrusted content is still caught (regression: existing
      tests pass) and, where practical, benefits from the P10-01 classifier rather than duplicating
      detection logic.
- [ ] New tests: an answer that leaks system-prompt text is redacted; a clean answer passes through
      unmodified (`modified=False`); an answer echoing an injected instruction from a fenced CV/crawl
      excerpt is stripped.
- [ ] `ruff`, `ruff format --check`, `mypy`, `pytest` all green.

## Design references
- dev-board/app-design-and-features.md §7 (output guardrails bullet), §7.3 (untrusted content point 4)
- `backend/app/guardrails/heuristics.py` — `screen_output`, `_DENY_PATTERNS`, `OutputScreenResult`
- dev-board/code-review/P10-01-injection-classifier/ — read `engineer.md` if it landed first (reuse
  its detector for the output side if it exposes a scoring/detection call, not just an input gate)

## Constraints / non-goals
- Do not change how `screen_output` is wired into the responder flow unless the current wiring is
  actually broken — this is a detection-quality task, not a plumbing task.
- No new external paid dependency.
