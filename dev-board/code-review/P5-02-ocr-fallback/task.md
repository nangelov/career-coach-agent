# Task P5-02-ocr-fallback — Type/text-layer detect + OCR fallback (Tesseract/OCRmyPDF)
- **Phase:** P5   **Status:** ENG   **Tags:** (B)

## Scope
tasks.md item: "Type detect + text-layer check; OCR fallback (Tesseract/OCRmyPDF) for scanned/image/slide CVs;
reserve VLM-OCR path for hard docs."

Builds on `P5-01-ingestion-parser` (`backend/app/ingestion/`: `DocumentParser` ABC, `ParsedDocument`,
`DoclingParser`). Add:
- A **type-detect + text-layer check** step: given an uploaded document, determine its format (PDF/DOCX/PPTX/
  image) and, for PDFs, whether it has a usable text layer. This can be an explicit probe (e.g. quick
  page-text extraction) or read off `DoclingParser`'s output (`ParsedDocument.is_empty` / low text density) —
  follow the design-review note left in `P5-01-ingestion-parser/architecture-review.md`: the OCR fallback must
  trigger off a real "no/low usable text" signal, not be reinvented from scratch.
- An **OCR fallback engine** implementing the same `DocumentParser` interface, using Tesseract
  (`pytesseract`) and/or OCRmyPDF for scanned/image/slide-style CVs where the primary docling pass yields
  little/no text.
- A small **orchestrating wrapper** (e.g. `CompositeDocumentParser` or similar) that: tries the primary
  (docling) engine, detects "no usable text layer" via the check above, and falls back to the OCR engine when
  needed — still returning a `ParsedDocument`, so callers (P5-03 structuring, P5-04 endpoint) don't need to
  know which engine ultimately ran.
- **Reserve** (do not implement) a VLM-OCR path for hard documents that fail structured extraction even after
  OCR — leave a clear extension point (e.g. a documented seam / TODO / stub interface) per design §5.1's
  tiering, but do not wire an actual VLM call in this task.
- Add `pytesseract` / `ocrmypdf` (and Tesseract binary note for Docker/dev setup) as needed to
  `backend/pyproject.toml`; keep imports lazy like the docling adapter so CI collection doesn't require the
  OCR toolchain to be installed.
- Unit tests: a scanned/image-like fixture (or a fixture engineered to have no text layer) that exercises the
  fallback path, plus tests proving a normal text PDF/DOCX does NOT trigger OCR (stays on the primary engine).

## Acceptance criteria
- [ ] A type-detect / text-layer-check step exists and is testable in isolation.
- [ ] An OCR-based `DocumentParser` implementation exists (Tesseract and/or OCRmyPDF-backed).
- [ ] A composing parser tries docling first, falls back to OCR only when the primary output has no/low usable
      text, and exposes a single interface to callers.
- [ ] A documented extension point exists for a future VLM-OCR path (no implementation required).
- [ ] Unit tests cover: (a) fallback triggers on a low/no-text-layer fixture, (b) fallback does NOT trigger on
      a normal text document, (c) OCR engine's output conforms to `ParsedDocument`.
- [ ] `ruff`, `mypy`, and the full `pytest` suite pass (OCR-toolchain-dependent tests may skip gracefully in
      environments without Tesseract installed, mirroring the docling `importorskip` pattern from P5-01 —
      confirm this explicitly).

## Design references
- dev-board/plan.md: Phase 5 — Document Intelligence & CV/profile (line 97)
- dev-board/app-design-and-features.md: §5.1 Document Intelligence & OCR (lines 196-222) — pipeline diagram
  (text-layer? → direct extract vs rasterize→OCR), engine tiering table.
- dev-board/code-review/P5-01-ingestion-parser/architecture-review.md — Notes section: explicit guidance that
  the OCR fallback must key off `ParsedDocument.is_empty` (or a low-confidence signal), not reinvent detection.

## Constraints / non-goals
- No LLM-assisted structured-profile parsing — P5-03.
- No `POST /api/profile/cv` endpoint, no Celery task — P5-04.
- No actual VLM-OCR implementation — reserve the seam only.
- No frontend work — P5-07.
- Keep the OCR engine behind the same `DocumentParser` interface from P5-01 — no new parallel abstraction.
