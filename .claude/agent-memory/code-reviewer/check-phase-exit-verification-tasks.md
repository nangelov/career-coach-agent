---
name: check-phase-exit-verification-tasks
description: How to review P*-N-verify phase-exit verification tasks (test-only + incidental gate fixes)
metadata:
  type: project
---

Reviewing a `P*-NN-verify` task (e.g. P4-10-verify): the engineer adds a `test_pN_exit_verification.py`
composing prior-phase work end-to-end, and often flags an incidental gate fix.

**Why:** these tasks are verification-only (no product code), so the review reduces to two things: (a) does the
new test genuinely *prove* the criterion (not a weak/always-green test), and (b) is any bundled "mechanical"
fix truly zero-logic-change.

**How to apply:**
- **Reformat/gate-fix claims** ("mechanical `ruff format`, zero logic change"): `git diff` each *tracked* file
  and confirm every hunk is pure line-wrapping — same identifiers/args/values. New/untracked files carry no
  committed-logic risk. Then run `ruff format --check .` to confirm the gate is actually green.
- **Streaming assertions must be discriminating:** a real incremental-streaming test needs ≥2 token frames
  that reassemble the answer AND a check that no single frame carries the whole answer, ordered before `done`.
  A test that only asserts "a token event exists" would pass on a buffered response — flag that as weak.
- **Guardrail short-circuit tests** should use the LLM router as a spy and assert it was never called
  (`stream_messages == [] and complete_messages == []`), plus no `plan`/`error` events.
- **Don't gate on leaning on existing suites** for regression/frontend points — duplicating coverage is a
  DRY/YAGNI violation; the task's job is to confirm they compose + are green together.
- **Run all four gates yourself** (ruff check, ruff format --check, mypy, pytest) + the frontend suite; the
  report's numbers should reproduce exactly. Related: [[check-cross-cutting-drift]].
