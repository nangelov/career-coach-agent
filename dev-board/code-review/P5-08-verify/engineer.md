# Engineer report — P5-08-verify · Revision 1

## Summary

Verified the **full P5 exit criterion** — *"a scanned/image PDF and a PPTX CV both parse
(async, with progress) into a usable structured profile and become RAG-grounded"* — end to
end. P5-01..P5-07 already cover the criterion in pieces across their own suites, but **no
single test composed the whole chain** (scanned-PDF OCR fallback → structuring →
async-upload/status → persist → reuse → RAG retrieval), and several exit-criterion
sub-assertions were only proven in isolation with fakes standing in for *both* sides of a seam
(e.g. `run_cv_ingestion` was only exercised with a `FakeParser`, never the real
`CompositeDocumentParser` tiering; the P5 persist and the P4 retrieval were never proven to
share one pgvector store).

Added one cohesive verification module — `backend/tests/test_p5_exit_verification.py` (8 tests,
mirroring `test_p4_exit_verification.py`) — that drives the **real** composite parser
(tiering + text-layer check), the **real** `ProfileStructurer`, the **real** Celery task core
`run_cv_ingestion`, the **real** `POST /api/profile/cv` / `GET /api/jobs/status/{task_id}` /
`GET /api/profile` routers, and the **real** P4 RAG retrieval path
(`retrieve` → `hybrid_search_chunks`). Only the true external edges are faked — docling's
layout/OCR *model* download, the Tesseract/OCRmyPDF *binary*, LLM completions, embeddings, and
the Celery broker — exactly the P4-10 posture ("real stack, fake the outermost collaborators").
The **PPTX** path uses the **genuine docling engine** (its office pipeline needs no model
download; guarded by `importorskip("docling")` since the curated CI venv excludes docling).

Added two real fixtures the task's fixture note asked for:
`backend/tests/fixtures/ingestion/scanned_cv.pdf` (a genuinely rasterized, **image-only** PDF —
no text layer) and `.../sample_cv.pptx` (a real slide CV).

**Conclusion: the current implementation meets the full P5 exit criterion as written.** No
implementation gap was found in P5-01..P5-07 — all seven points are covered (see the table
below). The two live-Postgres proofs were **run green against docker-compose Postgres** (brought
up, migrated, executed, torn down) and also skip cleanly where no DB is reachable, matching the
P2-09/P4-10 precedent.

## Files changed

- `backend/tests/test_p5_exit_verification.py` — **new.** The composed P5 exit verification (8
  tests). Verification-only: **no product code changed** (task constraint honored).
- `backend/tests/fixtures/ingestion/scanned_cv.pdf` — **new.** A genuine image-only (rasterized)
  PDF CV — no text layer, so docling's direct extract is empty and the real composite must fall
  back to OCR. Generated via PIL (raster page saved as PDF).
- `backend/tests/fixtures/ingestion/sample_cv.pptx` — **new.** A real PPTX CV (python-pptx) the
  genuine docling office pipeline parses offline.

## Key decisions

- **Compose the real ingestion chain; fake only the true external edges** (task points 1–6,
  design §5.1/§5.3). The module wires the *real* `CompositeDocumentParser(primary=DoclingParser,
  fallbacks=(OcrDocumentParser,))` with the docling convert backend and the OCR engine injected
  via their existing `converter_factory` / `engine_factory` seams — so the **real** tiering,
  **real** `TextLayerCheck` verdict, and **real** metadata annotation decide *when* OCR runs.
  Only the model download (unavailable) and the `tesseract` binary (not installed) are faked.
- **The PPTX path runs the genuine docling engine** (point 2). docling's office pipeline needs no
  model download (verified: converts a PPTX in <0.1s offline), so this proves the primary tier on
  a real slide document rather than a stubbed converter. `importorskip("docling")` keeps it CI-safe
  (the curated venv omits docling).
- **Prove the parse actually feeds structuring** (points 1/2/4): the fake structuring completer
  records the messages it received, and each test asserts the recovered CV text ("Data Engineer")
  reached the LLM — so parse→structure is proven *wired*, not two independently-faked halves. The
  "usable profile" assertion (point 4) requires **non-empty skills + experience + education** — an
  all-empty profile from a real CV fails, per the task.
- **Prove async is real, not scripted** (point 3): (a) the real `POST /api/profile/cv` returns
  `202`+`task_id` and the captured enqueue payload base64-decodes to the *exact uploaded bytes*
  (direct evidence the parse was deferred off the request path, not run in-request); (b) the real
  `GET /api/jobs/status` surfaces the producer lifecycle `pending → in_progress(parsing →
  structuring → persisting) → success` using the producer's own `STATE_*` constants and result
  shape (so any producer/consumer drift fails); (c) the real `run_cv_ingestion` core emits genuine
  ordered `PARSING → STRUCTURING` transitions for **both** documents.
- **Prove P5 ingestion and P4 retrieval share one store** (point 6, the crux): the live-DB test
  persists a CV via the real task core, then runs the **real** RAG `retrieve` over the **same**
  provider and asserts the returned citation's chunk belongs to a `KbDocument` with
  `source_type == "user_cv"` and this user's id. An always-green offline seam test
  (`test_rag_retrieve_surfaces_the_user_cv_chunk_offline`) drives the real `retrieve` +
  `hybrid_search_chunks` over the post-ingestion DB shape so point 6 has coverage even without a DB.
- **Live-DB tests skip cleanly without Postgres** (mirroring `test_profile_ingest_persistence` /
  P4-10) — but were actually executed green here against compose Postgres, so they're not
  untested. Re-upload-replace ("exactly one `user_cv` doc", point 5) is already proven by the
  existing `test_profile_ingest_persistence`; not duplicated (DRY) — referenced in the table.

## P5 exit criterion — point-by-point

| # | Criterion | Where proven |
|---|-----------|--------------|
| 1 | Scanned/image PDF → **OCR fallback** (not docling primary) → non-trivial profile | **new** `test_scanned_pdf_triggers_ocr_fallback_into_structured_profile` (real composite; asserts `ocr_fallback_used=True` + OCR engine invoked on the PDF) |
| 2 | PPTX → **docling primary** → structured profile | **new** `test_pptx_cv_parses_via_docling_primary_into_structured_profile` (**real docling**; asserts `ocr_fallback_used=False`, OCR tier never reached) |
| 3 | Async: `202`+`task_id`, no in-request parse; status pending→in-progress(stage)→success | **new** `test_upload_endpoint_is_async_202_and_no_in_request_parse` + `test_job_status_polls_producer_lifecycle_to_success` + `test_task_core_emits_real_progress_stages_for_both_documents` |
| 4 | Usable profile (non-empty skills/experience/education for a real CV) | asserted in points 1 & 2 via `_assert_usable_profile` (empty profile ⇒ fail) |
| 5 | Persisted + reusable: `GET /api/profile` returns it, no re-upload; re-upload keeps one CV | **new** `test_persisted_profile_is_reusable_via_get_profile` (live DB) + existing `test_profile_ingest_persistence` (re-upload replace) |
| 6 | RAG-grounded: CV chunks retrievable by the P4 RAG agent as `source_type=="user_cv"` | **new** `test_cv_chunks_are_rag_grounded_live` (live DB, authoritative) + `test_rag_retrieve_surfaces_the_user_cv_chunk_offline` (offline seam) |
| 7 | Frontend upload/progress/view-edit works against this contract | existing `frontend/__tests__/profile.test.ts` + `CvUpload.test.tsx` + `ProfileView.test.tsx` — green in the full run |

## Pre-existing mypy noise (P5-06 flag) — current state

The `tests/`-scope mypy noise flagged in `P5-06-task-status/engineer.md` is **still present and
unchanged** — `mypy app tests` reports **7 errors in 4 files**: `tests/test_llm_router.py`,
`tests/test_ingestion_parser.py`, `tests/test_ingestion_ocr.py` (4× `unused-ignore`), and
`tests/test_p4_exit_verification.py` (a langgraph node-type `arg-type`). It is **non-gating** —
CI's mypy gate is scoped to `app/`+`migrations/` (both clean). My **new test file adds 0 errors**
to this count (`mypy tests/test_p5_exit_verification.py` → clean). Not fixed here (out of P5-08
scope — it belongs to those tasks' files); reported so it isn't silently lost track of.

## How to verify

```bash
# Backend (from backend/) — mirrors `make check`:
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy app/ migrations/
uv run --no-sync pytest -q                                   # offline (live-DB tests skip)
uv run --no-sync pytest tests/test_p5_exit_verification.py -v
# Full live-DB pass (actually run here, green):
make test-integration-full        # brings up compose Postgres, migrates, runs all, tears down

# Frontend (from frontend/) — mirrors frontend-ci.yml:
npm run lint && npm run build && npm test -- --watchAll=false
```

## Tests (final step — mandatory)

**Backend** (`backend/`):
- `ruff check .` → **All checks passed!**
- `ruff format --check .` → **156 files already formatted**
- `mypy app/ migrations/` → **Success: no issues found in 94 source files**
- `pytest -q` (offline) → **411 passed, 49 skipped** (+6 new offline; +2 new live-DB tests skip
  without Postgres — same convention as the rest of the P5/P2 live suites)
- **Live DB** (`make`-style: compose Postgres up + `alembic upgrade head`): full suite
  **459 passed, 1 skipped**; `test_p5_exit_verification.py` **8 passed** (both live-DB proofs
  green — persist→reuse and RAG grounding against real `vector(4096)`+JSONB). DB torn down after.
- `mypy tests/test_p5_exit_verification.py` → **Success** (my new file adds no mypy noise).

**Frontend** (`frontend/`):
- `npm run lint` → **✔ No ESLint warnings or errors**
- `npm run build` → **compiled successfully** (all routes emitted)
- `npm test` → **9 suites, 89 passed**

No failing tests. No test weakened or deleted; no product code changed.

## Self-check

- [x] Meets acceptance criteria — all 7 P5 exit points covered by composed/integration tests;
  live-infra parts documented and actually run green against compose Postgres; report states the
  criterion **is met** with no gap in P5-01..P5-07.
- [x] No secrets committed; verification-only (no product code changed); Router→Service→Task/Repo
  layering respected (tests drive the real layered stack, faking only external edges).
- [x] Full backend suite green (ruff / ruff format / mypy `app/`+`migrations/` / pytest) — results
  pasted. Full frontend suite green (lint / build / jest) — results pasted.
- [x] P5-06 mypy `tests/`-scope noise explicitly re-checked and reported (still present,
  unchanged, non-gating; my new file clean).
