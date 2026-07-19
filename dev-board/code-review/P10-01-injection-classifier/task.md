# Task P10-01-injection-classifier — S8: real injection/jailbreak classifier

- **Phase:** P10   **Status:** ENG   **Tags:** (B)

## Scope
Replace the regex deny-list in `app/guardrails/heuristics.py::screen_input` with a real
jailbreak / prompt-injection **classifier** (design §7.4, plan.md S8). The P4 heuristic is an
honest placeholder ("stops nobody") — this task is where it was always meant to be replaced.

- Pick a free/OSS, self-hostable classifier consistent with the locked budget posture (§11):
  a HF `Prompt-Guard`-family model (e.g. `meta-llama/Llama-Prompt-Guard-2-86M` or similar) is
  the design's suggested option (plan.md S8: "Prompt-Guard / Llama-Guard"). Run it the same way
  embeddings are run (P2-06 precedent): **in-process** via `transformers` (small model, CPU-fine,
  no per-call API cost) — do **not** add a paid inference dependency. If in-process is not
  feasible in the time box, an HF Inference Providers free-tier text-classification call is the
  fallback — document the tradeoff either way.
- Preserve the existing **contract**: `screen_input(message: str) -> SafetyVerdict` (stage=INPUT),
  used by `app.agents.graph.route_after_input_guardrail`. Do not touch the graph wiring — only the
  detection internals.
- Keep the deny-list as a **fast-path pre-filter** (cheap, catches the obvious cases before the
  model call) is optional/your call — but the classifier must be the actual gate, not cosmetic.
- Verdict must never leak *why* a message was blocked to the user — keep `REFUSAL_MESSAGE` generic;
  categories/scores are internal telemetry only (existing pattern in `heuristics.py`).
- Add config for the model name/threshold in `app/config.py` (curated deps: see P8-08 guard —
  new deps must be added to backend CI's curated dependency list, not left "any version").
- This task does **not** cover topic scoping (already done: planner intent classification, P4/P6)
  or abuse/off-topic filtering or PII scrubbing (P10-02) or output guardrails (P10-03) — stay scoped
  to input jailbreak/injection detection.

## Acceptance criteria
- [ ] `screen_input` uses a real classifier (not only regex) to detect jailbreak/prompt-injection
      attempts, still returning `SafetyVerdict(stage=INPUT, ...)`.
- [ ] Existing `test_input_guardrails.py` / `test_topic_guardrail.py` still pass (update fixtures
      if the detection mechanism changes what triggers a block — do not weaken assertions to make
      them pass trivially).
- [ ] New unit tests cover: a clean classifier block, a clean classifier allow, and a
      classifier-unavailable fallback (fail safe — decide and document open vs. closed failure mode).
- [ ] No new paid/unbounded-cost dependency; new deps added to the backend CI curated dependency list.
- [ ] `ruff`, `ruff format --check`, `mypy`, `pytest` all green.

## Design references
- dev-board/app-design-and-features.md §7.4 (topic scoping / guardrail layering), §7 (input guardrails)
- dev-board/plan.md — Security & privacy sequencing table, row **S8**
- dev-board/code-review/P4-08-input-guardrails-minimal/ — the placeholder this replaces
- `.claude/agent-memory/system-architect/ruling-input-guardrail-p4-08-seam.md` — the seam contract

## Constraints / non-goals
- No arbitrary code execution, no new external paid service.
- Don't change `app/guardrails/__init__.py`'s exported contract (`screen_input`, `screen_output`,
  `REFUSAL_MESSAGE`, `fence_untrusted`) unless required — keep the graph-facing seam stable.
