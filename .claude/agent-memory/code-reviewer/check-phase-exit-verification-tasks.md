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
- **Flagged prior-task defect → route, don't gate the verify task:** when the engineer of a verify task
  precisely flags a real latent bug in a *prior* task (e.g. P6-09 flagged P6-04 canonicalization), it is
  correctly *deferred* for the verify task, NOT a blocker — verify tasks are product-code-free and the task
  itself instructs "flag precisely, route to the owning task, don't patch around." Confirm the bug is real
  (I verified P6-04's), record it as a note/finding routed to the owning task, and still APPROVE the verify
  task if its own deliverable (test module + gates + honest report) is sound. But call the caveat out loudly.
- **P6-04 curated-corpus canonicalization drift (real, route to P6-04):** `_resolve_baseline` searches
  `shared_kb_document_ids(source_types=["curated"])` and takes the top hybrid hit (`k=1`, no threshold). The
  curated corpus holds taxonomy occupations AND mined role-profile summaries (`ROLE_PROFILE_SOURCE_TYPE=
  "curated"`, title `"Market requirements: <role>"`) AND learning resources — all `source_type="curated"`,
  distinguished only by `meta.kind`. So read-time canonicalization can drift to a summary title →
  `get_role_profile` miss → perpetual `202` re-enqueue loop. Holds only because the occupation empirically
  outranks the summary under seeded taxonomy. Fix: filter by `meta.kind`, not `source_type` alone.
- **Watch stubbed-resolver cache-reuse proofs:** P6-09's cache-reuse test injects a `_SpyResolver` (stub), so
  it never exercises the real canonicalization; the live round-trip *skips* exactly when canonicalization
  drifts — so "criterion met" is conditional on the ranking holding, not proven robust. Fine for scope, but
  note it so the orchestrator doesn't over-read the conclusion.
- **Live-Postgres proofs (persist/reuse, RAG-grounding) skip without a DB** — you usually can't confirm them;
  read the code for correctness (create user → real task core → assert via real endpoint/`retrieve` → cascade
  cleanup) and trust the engineer's compose-Postgres run per the P2-09/P4-10 posture.
