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
- **Seam scrutiny for ingestion-chain verifies (P5-08 pattern):** when a test reads a "genuine" fixture but
  the bytes flow into a *source-ignoring* fake (e.g. `_FakeConverter.convert`/`_FakeOcrEngine.extract_text`
  return canned output regardless of input), the fixture is **non-load-bearing** — the test proves the
  real *tiering/decision* logic (`CompositeDocumentParser` + `TextLayerCheck` → `ocr_fallback_used`), not
  that a real scanned PDF yields an empty text layer. That's fine given the no-docling-model constraint, but
  it's a nit, not the "real parse" proof; don't let the report imply otherwise.
- **Real-docling proofs are local-only:** the genuine-parse test is `importorskip("docling")`-guarded and
  **skips in the curated CI venv** — it only ran because docling is in the local dev venv. Run it yourself to
  confirm it actually passes (not just collects); in CI that point is skipped.
- **Both-sides-faked broker seam is acceptable when tied by a contract:** upload-endpoint test uses a
  capturing enqueuer (never runs the task) + task-core test calls `run_cv_ingestion` directly (never via the
  endpoint) — legitimate (broker is a true external edge) *only* because a byte-equality assertion
  (`base64decode(captured) == uploaded`) ties the two halves. Confirm that tie exists; note there's no single
  upload→task→persist→retrieve flow test (chain proven in segments).
- **Live-Postgres proofs (persist/reuse, RAG-grounding) skip without a DB** — you usually can't confirm them;
  read the code for correctness (create user → real task core → assert via real endpoint/`retrieve` → cascade
  cleanup) and trust the engineer's compose-Postgres run per the P2-09/P4-10 posture.
