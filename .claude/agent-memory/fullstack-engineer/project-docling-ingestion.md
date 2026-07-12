---
name: docling-ingestion
description: P5 ingestion — DocumentParser ABC + DoclingParser conventions; how to test docling offline/CI
metadata:
  type: project
---

P5 document ingestion (`app/ingestion/`) follows the same ports-and-adapters shape as
[[project-hybrid-search-rrf]] embeddings: `DocumentParser` ABC (parser.py) + `DoclingParser`
adapter (docling_parser.py) + `ParsedDocument` pydantic result (types.py). `DocumentSource = str | bytes`.

**Why:** docling pulls torch + layout/OCR models and is **excluded from the CI curated venv**
(same as sentence-transformers — see [[project-uv-ci-heavy-deps]]).

**How to apply:**
- Import `docling` **lazily inside methods** (deferred `import`), never at module top or in
  `__init__`, so `app.ingestion` imports at collection time in CI without the ML stack.
- Put the converter behind an injectable `converter_factory` seam; tests inject a fake mimicking
  docling's `ConversionResult` shape (`.status.name`, `.input.format.value`, `.input.page_count`,
  `.document.export_to_markdown/text/dict()`).
- Real end-to-end test: use a **DOCX** fixture — docling's DOCX path uses the simple pipeline and
  needs **no model download** (offline/sandbox-safe). PDF/image trigger a layout-model download —
  avoid until a later P5 subtask. Guard real-docling tests with `pytest.importorskip("docling")`.
- `bytes` sources need a filename/media_type hint → wrap in `docling_core.types.io.DocumentStream`.

**P5-02 OCR fallback** extends this: `TextLayerCheck` (text_layer.py) decides usable-text-vs-OCR
off `ParsedDocument.is_empty` + chars/page density (do NOT re-probe raw bytes — architect ruling).
`OcrDocumentParser` (Tesseract/OCRmyPDF, lazy imports + injectable `engine_factory`) is just another
`DocumentParser`. `CompositeDocumentParser` takes `primary` + ordered `fallbacks` chain — that chain
IS the VLM extension point (`ReservedVlmOcrParser` stub raises NotImplementedError). Shared
MIME→ext map lives in formats.py (DRY across docling + OCR). pytesseract/ocrmypdf excluded from
curated CI venv; real-OCR test guarded by importorskip + `pytesseract.get_tesseract_version()` probe.
