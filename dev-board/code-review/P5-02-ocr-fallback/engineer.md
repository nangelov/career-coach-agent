# Engineer report — P5-02-ocr-fallback · Revision 1

## Summary
Adds the OCR fallback tier to the P5-01 ingestion module, behind the existing
`DocumentParser` seam (no new parallel abstraction). Three pieces plus a reserved seam:

1. **Text-layer check** (`text_layer.py`) — a pure, side-effect-free `TextLayerCheck.assess()`
   that decides "usable text layer vs. needs OCR" off the **real** primary-engine signal
   (`ParsedDocument.is_empty` + a chars-per-page density floor), exactly as the P5-01
   architecture-review note required (do not reinvent detection). Testable in isolation.
2. **OCR engine** (`ocr_parser.py`) — `OcrDocumentParser`, a `DocumentParser` backed by
   Tesseract (images) / OCRmyPDF (PDF). Same lazy-import + injectable-seam shape as
   `DoclingParser`: the OCR toolchain (`pytesseract`, `PIL`, `ocrmypdf`) is imported inside
   the methods that use it, and the backend is behind an injectable `engine_factory` so
   CI/tests need no binaries.
3. **Composite** (`composite_parser.py`) — `CompositeDocumentParser` runs the primary,
   asks `TextLayerCheck`, and only on a no/low-text verdict walks an **ordered `fallbacks`**
   chain (OCR today), returning the first tier with a usable text layer and otherwise the
   best-effort extract. Exposes the single `DocumentParser` interface, so P5-03/P5-04 callers
   don't learn which engine ran. `build_default_composite_parser()` wires docling → OCR.
4. **Reserved VLM seam** (`vlm.py`) — `ReservedVlmOcrParser`, a `DocumentParser` whose
   `parse()` raises `NotImplementedError`; the ordered fallback chain is the documented
   extension point for §5.1's VLM last-resort tier (no VLM call wired, per task).

Also: a small **DRY** extraction — the shared MIME→extension map + format detection moved to
`formats.py`, consumed by both `DoclingParser` (stream-name hint) and `OcrDocumentParser`
(image-vs-PDF routing). Added `pytesseract`/`ocrmypdf` to `pyproject.toml` with a Docker/dev
binary note; kept them out of the curated CI venv (lazy imports).

## Files changed
- `backend/app/ingestion/formats.py` — NEW. Shared `MEDIA_TYPE_EXTENSIONS` map +
  `detect_format()` / `extension_for_media_type()` (DRY across the two engines).
- `backend/app/ingestion/text_layer.py` — NEW. `TextLayerCheck` + `TextLayerAssessment`
  (the usable-text-layer decision; keys off `ParsedDocument.is_empty` + density).
- `backend/app/ingestion/ocr_parser.py` — NEW. `OcrDocumentParser`, `OcrEngine` protocol,
  `TesseractOcrEngine` (Tesseract/OCRmyPDF, lazy imports, injectable seam).
- `backend/app/ingestion/composite_parser.py` — NEW. `CompositeDocumentParser` (tiered chain)
  + `build_default_composite_parser()`.
- `backend/app/ingestion/vlm.py` — NEW. `ReservedVlmOcrParser` — the documented, unimplemented
  §5.1 VLM last-resort seam.
- `backend/app/ingestion/docling_parser.py` — use shared `extension_for_media_type()` instead
  of its own local map (DRY; no behavior change).
- `backend/app/ingestion/__init__.py` — export the new public symbols.
- `backend/pyproject.toml` — add `pytesseract>=0.3.10`, `ocrmypdf>=15.0.0` with a
  system-binary note (`tesseract-ocr ghostscript qpdf`).
- `backend/tests/test_ingestion_ocr.py` — NEW. Unit tests (text-layer check, OCR parser via
  fake engine, composite tiering via fake parsers, VLM seam) + one real-Tesseract test
  guarded by `importorskip` + a binary probe.

## Key decisions
- **Fallback triggers off `ParsedDocument.is_empty` + density, not a re-probe** (design §5.1;
  P5-01 architecture-review Notes). `TextLayerCheck` is the single decision node the pipeline
  diagram's "has text layer?" branch maps to. Type detection stays delegated to the engine
  (`ParsedDocument.source_format`); this step only adds the text-layer verdict.
- **OCR is a `DocumentParser`, orchestration is a `DocumentParser`** — no new abstraction
  (task constraint). Callers depend only on `parse()`; the composite is itself swappable.
- **Ordered `fallbacks` chain, not a hard-coded primary+single-fallback** — this *is* the
  VLM extension point (§5.1 tiering: docling → Tesseract/OCRmyPDF → VLM). `ReservedVlmOcrParser`
  already conforms to the interface, so enabling the tier later is purely additive.
- **Lazy imports + injectable `engine_factory`** — mirrors the blessed `DoclingParser` /
  `SentenceTransformerEmbeddingClient` posture so the OCR toolchain stays out of the curated
  CI venv and tests run without binaries.
- **OCR scope = images (Tesseract) + PDF (OCRmyPDF)**; DOCX/PPTX rendering is not done here
  (needs a headless renderer) — documented as future/VLM-tier work. Unsupported formats raise
  `UnsupportedDocumentError`, which the composite catches to degrade gracefully.
- **Composite annotates result metadata** (`ocr_fallback_used`, `text_layer_usable`,
  `text_layer_reason`, `text_char_count`) via `model_copy` — observability without changing
  the engine-agnostic `ParsedDocument` shape; all JSON-serializable.

## How to verify
```bash
cd backend
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy app/ migrations/
# ingestion only:
.venv/bin/python -m pytest tests/test_ingestion_ocr.py tests/test_ingestion_parser.py -q
# full suite (live DB env from root .env):
set -a && . ../.env && set +a && .venv/bin/python -m pytest -q
```

## Tests (final step — mandatory)
- `ruff check .` → All checks passed. `ruff format --check .` → 136 files already formatted.
- `mypy app/ migrations/` (strict) → Success: no issues found in 83 source files.
- `pytest tests/test_ingestion_ocr.py tests/test_ingestion_parser.py` → **35 passed, 1 skipped**
  (the 1 skip = real-Tesseract test; the `tesseract` binary is not installed in this env, so
  it `importorskip`s / binary-probe-skips — the P5-01 `importorskip` pattern, confirmed).
- **Full suite** (live DB env): `347 passed, 44 skipped` — no failures. Skips are the usual
  heavy/optional-toolchain and env-gated tests (docling/tesseract real-engine, etc.).
- No failures to root-cause.

## Self-check
- [x] Meets acceptance criteria: text-layer check testable in isolation; OCR `DocumentParser`
  exists (Tesseract/OCRmyPDF); composite tries docling→OCR only on no/low text, single
  interface; documented VLM seam (`ReservedVlmOcrParser`, not implemented); tests cover
  (a) fallback triggers on no-text, (b) does NOT trigger on normal text, (c) OCR output is a
  `ParsedDocument`; ruff/mypy/pytest green with graceful OCR-toolchain skips.
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (pure interface +
  adapters below services; no router/DB/Celery wiring — those are P5-03/P5-04).
- [x] Tests/lints pass (pasted above).
