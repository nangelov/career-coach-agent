---
name: phase-exit-verification
description: How to compose a Px-NN-verify phase-exit test — real stack, fake only true external edges, live-DB skip
metadata:
  type: feedback
---

Phase-exit verification tasks (`Px-NN-verify`, e.g. P4-10, P5-08) must prove the WHOLE chain
end-to-end in one composed module, not just re-run each prior task's isolated suite.

**Why:** prior per-task tests fake *both* sides of a seam (e.g. P5's `run_cv_ingestion` was only
tested with a `FakeParser`; P5 persist and P4 retrieval were never proven to share one pgvector
store). The verify task's value is proving they *compose*.

**How to apply:**
- Add `tests/test_pN_exit_verification.py`; drive the REAL layered stack (real
  services/routers/parsers/agents), fake ONLY the true external edges: LLM completions,
  embeddings, model downloads, system binaries, live network, the Celery broker. Mirror the most
  recent `*_exit_verification.py` for shape.
- Prove a seam is *wired* (not two independently-faked halves): have the fake record what it
  received and assert the upstream output actually reached it.
- Ingestion (P5) injection seams for the fakes: `DoclingParser(converter_factory=..., document_stream_factory=...)`,
  `OcrDocumentParser(engine_factory=...)`, `ProfileStructurer(<LLMCompleter fake returning a
  forced record_profile tool call>)`, `run_cv_ingestion(..., embedder=<fixed vector(4096)>)`.
  docling's OFFICE pipeline (pptx/docx) runs offline with no model download — use the real engine
  there under `pytest.importorskip("docling")` (curated CI venv excludes docling). PDF/image OCR
  needs models+`tesseract` binary → fake those.
- Live-DB proofs (real pgvector/JSONB): copy the `_postgres_reachable()` + provider fixture that
  `pytest.skip`s when no DB — CI/offline skips cleanly. BUT actually run them once via
  `make test-integration-full` (compose up → alembic upgrade head → pytest → down) and report
  green; don't hand off untested live tests. Non-degenerate embedding vector ([0.1]*4096), not
  zeros (pgvector cosine on a zero vector is NaN); the lexical ts_rank half carries keyword hits.
- Report point-by-point (a table mapping each exit-criterion clause → the test). State a clear
  yes/no on the criterion, and FLAG (don't silently patch) any gap that belongs to a prior task.
- Fake→Protocol seams: a bare `Callable`/lambda-with-default-arg trips mypy ("Cannot infer type of
  lambda" / arg-type). Use a named inner `def factory(task_id: str) -> X` and annotate the OUTER
  return as the Protocol type itself (e.g. `-> AsyncResultFactory`), not `Callable[[str], X]`.
