# Code review — P5-08-verify · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | tests/test_p5_exit_verification.py:326-355 | In the scanned-PDF test (point 1), the real fixture bytes flow to a **fake** docling converter that ignores its source (returns empty text unconditionally) and to a **fake** OCR engine that ignores its source (returns canned text). The test genuinely proves the *composite tiering* decision (empty primary → OCR fallback + `ocr_fallback_used` metadata via the real `TextLayerCheck`), but the "genuinely rasterized, image-only" `scanned_cv.pdf` fixture is **not load-bearing** — the test would pass with any bytes. Inherent to the no-docling-model constraint and honestly acknowledged. | Optional: assert something derived from the fixture (e.g. its byte length reaching the parser) or drop the claim that the fixture's image-only nature is what the test proves. No change required. |
| C2 | nit | tests/test_p5_exit_verification.py:548-573 | The offline point-6 seam test's docstring claims it "proves the retrieval half consumes exactly what the P5 persist step writes." It actually drives `retrieve` over a **hand-built** `kb_chunk_row` (via `rag_db_one_hit`), not the real persist step's output, so it does not prove persist/retrieve shape-compatibility — only that `retrieve` maps a row to a citation. The **live** test (`test_cv_chunks_are_rag_grounded_live`) is the real proof and is correctly labelled authoritative. | Optional: soften the offline docstring to "drives the real retrieval path over a post-ingestion-shaped row"; the live test carries point 6. |
| C3 | nit | tests/test_p5_exit_verification.py:499-542 | The real task core's `STATE_PERSISTING` transition is never asserted offline: the guest-path core test returns before persisting (asserts only `[PARSING, STRUCTURING]`), and the status-lifecycle test drives `STATE_PERSISTING` through a **fake** `AsyncResult`. The real core emitting PERSISTING is only exercised (not asserted-on) via the live-DB persist path. Point 3 is still adequately covered. | Optional: no change required; note for completeness. |

## Notes
**Scope & method.** Verification-only task (new `tests/test_p5_exit_verification.py` + two fixtures;
`git`-confirmed no product code changed). I read the real code behind every seam
(`composite_parser`, `docling_parser`, `text_layer`, `ocr_parser`, `structuring`,
`tasks/profile_ingest`, `agents/rag_agent`, `tests/fakes`), inspected the fixtures, and ran the
suite, ruff, ruff-format and mypy myself.

**The tests are genuinely composed/integration-level, not trivially double-faked.** The seams are
placed at legitimate external edges only:
- Point 1/2 drive the **real** `CompositeDocumentParser` + **real** `TextLayerCheck` +
  `DoclingParser`/`OcrDocumentParser` wiring — the tiering, the empty-text-layer verdict, and the
  `ocr_fallback_used` metadata are all produced by real code; only the docling model download and
  the Tesseract binary are faked.
- **Point 2 ran against real docling and PASSED in this environment** (docling is installed in the
  local venv; it is `importorskip`-guarded and skips only in the curated CI venv). Verified the
  PPTX fixture genuinely contains "Data Engineer"/"Python"/"SQL"/"Spark".
- The fixtures are real: `scanned_cv.pdf` is a 1-page PDF v1.4 with **no text layer** (`pdftotext`
  yields nothing; no font/text objects) — a true image-only doc; `sample_cv.pptx` is a genuine
  PowerPoint 2007+ file.
- Point 3's "no in-request parse" is proven by decoding the captured enqueue payload and asserting
  it equals the exact uploaded bytes — solid evidence the parse was deferred, driven through the
  **real** router + `ProfileIngestService`.
- Structuring runs the **real** `ProfileStructurer` (real forced-tool-call validation); only the
  LLM completion is scripted, and the test asserts the recovered CV text actually reached the
  completer (parse→structure proven wired, not two independently-faked halves).

**One acceptable both-sides-faked seam:** the Celery-broker boundary. The upload-endpoint test uses
a capturing enqueuer (does not run the task) and the task-core test calls `run_cv_ingestion`
directly (not via the endpoint); they are tied only by the byte-equality contract. This is the true
external edge the task explicitly permits faking, and the byte contract is a reasonable tie — but
note there is no single test driving upload→task→status→persist→retrieve as one continuous flow; the
chain is proven in validated segments. Not a defect.

**Claims verified independently (all hold up):**
- `pytest -q` offline → **411 passed, 49 skipped** (matches report). New suite: 6 passed, 2
  live-DB skipped.
- `ruff check` / `ruff format --check` / `mypy tests/test_p5_exit_verification.py` → all clean.
- `mypy app/ migrations/` (CI scope) → **Success, 94 files**.
- Pre-existing `tests/`-scope mypy noise → **7 errors in exactly the 4 files** named in
  P5-06 (`test_llm_router`, `test_ingestion_parser`, `test_ingestion_ocr` ×4, `test_p4_exit_verification`);
  the new file adds **0**. Non-gating (CI mypy scope excludes `tests/`). Report accurate.

**Could not independently confirm:** the two live-Postgres proofs (points 5 & 6 authoritative) skip
here (no DB reachable), as designed. The code is correct on inspection (create user → ingest via
real task core → assert `GET /api/profile` round-trip / real `retrieve` returns a `user_cv` chunk →
cascade cleanup), and the engineer reports running them green against compose Postgres, consistent
with the P2-09/P4-10 precedent. Trusting that per the documented posture.

**Point-by-point exit-criterion claims hold.** All 7 points are covered by composed/integration
tests (or documented live-infra runs); the report's conclusion — the current implementation **meets
the full P5 exit criterion with no gap found in P5-01..P5-07** — is supported by what I could
execute and read. All three findings are nits (docstring precision / non-load-bearing fixture in one
test / an un-asserted-but-exercised stage); none affect correctness, security, or the verdict.
