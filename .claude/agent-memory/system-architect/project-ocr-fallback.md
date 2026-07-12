---
name: project-ocr-fallback
description: Blessed P5-02 OCR fallback design — text-layer check + composite tiering behind the P5-01 DocumentParser seam; VLM tier reserved
metadata:
  type: project
---

P5-02 (OCR fallback) APPROVED rev 1. Blessed ingestion tiering pattern, for P5-03/P5-04 and any future VLM tier.

- **OCR fallback triggers off the real primary signal, not a re-probe:** `TextLayerCheck.assess()` (pure fn over `ParsedDocument`) keys off `ParsedDocument.is_empty` + a chars/page density floor. This is the P5-01 architecture-review note honored — do not accept a from-scratch text-layer re-detection.
- **No new abstraction:** OCR engine (`OcrDocumentParser`) and orchestration (`CompositeDocumentParser`) both subclass the P5-01 `DocumentParser` ABC. Composite takes injected `primary`/`fallbacks`/`text_layer_check` ports. `OcrEngine` Protocol + injectable `engine_factory` seam (tests inject a fake, no binary needed).
- **VLM tier = reserved seam, not implemented:** `ReservedVlmOcrParser` is a real `DocumentParser` whose `parse()` raises `NotImplementedError`; the ordered `fallbacks` chain is the extension point. Enabling later is purely additive (append instance).
- **Exception hierarchy for graceful degradation:** `UnsupportedDocumentError` subclasses `DocumentParseError` (ingestion/parser.py); composite catches `DocumentParseError` to fall through tiers → callers always get a `ParsedDocument`.
- **Lazy-import posture (prior CI ruling):** `pytesseract`/PIL/`ocrmypdf` imported inside methods, kept out of curated CI venv; real-Tesseract test uses `importorskip`+binary-probe skip.
- **DRY:** shared MIME→ext map + `detect_format()` in `ingestion/formats.py`, consumed by both docling and OCR engines.

**Why:** §5.1 mandates a single `DocumentParser` interface so engines swap without touching agents; the pipeline diagram's "has text layer?" branch must be one decision node.
**How to apply:** For P5-04, hold to §5.1's "OCR runs as a Celery background job" — this task stayed sync (asyncio.to_thread) and deferred Celery. For P5-03, structuring must not assume rich `structured`/layout when OCR ran (OCR sets `structured={}`, `markdown==text`); check `ocr_fallback_used`/`text_layer_usable` metadata. See [[project-cr01-audit-rulings]] for the lazy-ML-import posture.
