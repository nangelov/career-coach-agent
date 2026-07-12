# Architecture review — P5-02-ocr-fallback · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Ingestion code lives in `backend/app/ingestion/` | `text_layer.py`, `ocr_parser.py`, `composite_parser.py`, `vlm.py`, `formats.py` all under `backend/app/ingestion/`; `__init__.py` exports the public symbols | none |
| A2 | §5.1 single `DocumentParser` seam | "Wrap all of this behind a single `DocumentParser` interface … so engines can be swapped without touching the agents" | Both `OcrDocumentParser` and `CompositeDocumentParser` subclass the P5-01 `DocumentParser` ABC; callers depend only on `parse()`; no new parallel abstraction introduced (task constraint honored) | none |
| A3 | §5.1 pipeline — "has text layer? → direct extract vs rasterize→OCR" | An explicit text-layer decision node keyed off a real primary signal | `TextLayerCheck.assess()` is a pure function over `ParsedDocument`, keying off `is_empty` + a chars/page density floor — exactly the P5-01 architecture-review note ("trigger off `ParsedDocument.is_empty`, do not reinvent detection") | none |
| A4 | §5.1 fallback engine = Tesseract/OCRmyPDF light tier | Tesseract (`pytesseract`) for images, OCRmyPDF for scanned PDFs | `OcrDocumentParser` + `TesseractOcrEngine`: `pytesseract`+PIL for raster images, `ocrmypdf` sidecar for PDF; DOCX/PPTX explicitly out of OCR scope (documented as VLM-tier work) | none |
| A5 | §5.1 tiering — VLM last-resort **reserved** | Documented extension point, no VLM call wired | `ReservedVlmOcrParser` is a real `DocumentParser` whose `parse()` raises `NotImplementedError`; ordered `fallbacks` chain is the seam (append the parser to enable). No VLM call present | none |
| A6 | Interfaces-before-implementations | OCR engine + backend swappable behind seams | `OcrEngine` Protocol + injectable `engine_factory`; composite takes `primary`/`fallbacks`/`text_layer_check` as injected ports; mirrors blessed `DoclingParser` / `SentenceTransformerEmbeddingClient` lazy-import + injectable-factory posture | none |
| A7 | Phase fit (P5 sequencing) | No LLM structuring (P5-03), no `POST /api/profile/cv` endpoint / Celery (P5-04), no embedding | None of those present; `build_default_composite_parser()` is a convenience wiring only, not consumed by any router/service yet — no premature coupling | none |
| A8 | Layering (§8) | Adapter/orchestration below services; no router/DB/Celery leaks | Pure interfaces + adapters; no repository, session, endpoint, or Celery access in any new file | none |
| A9 | Budget posture (§11) | free / OSS / self-hosted | Tesseract, OCRmyPDF, Ghostscript, qpdf all OSS/self-hosted; nothing paid; in-process | none |
| A10 | CI/ML posture (prior ruling) | Heavy toolchain deferred from curated CI venv; module importable at collection | `pytesseract`/`PIL`/`ocrmypdf` imported inside the methods that use them (deferred); `pyproject.toml` adds `pytesseract>=0.3.10`, `ocrmypdf>=15.0.0` with an apt-binary note; real-Tesseract test `importorskip`+binary-probe skips | none |
| A11 | DRY | No duplicated format map across the two engines | `formats.py` centralizes `MEDIA_TYPE_EXTENSIONS` + `detect_format()`; `docling_parser.py` refactored to consume it (no behavior change) | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — pure interface+adapter below services, no cross-layer leak
- [x] Honors locked decisions — no ReAct parser; no new datastore (OCR is in-process/file-temp only); SSO untouched; embeddings untouched
- [x] Interfaces-before-implementations — `DocumentParser` seam reused (not forked); `OcrEngine` Protocol + injectable factory; VLM tier is a typed, importable seam
- [x] Budget posture respected — Tesseract/OCRmyPDF/Ghostscript/qpdf all OSS/self-hosted, in-process

## Notes
- **Graceful degradation verified at the type level.** The composite's fallback loop catches `DocumentParseError`; `UnsupportedDocumentError` subclasses `DocumentParseError` (parser.py:27), so an OCR tier hitting a format it can't process (e.g. DOCX) degrades to the next tier / best-effort rather than propagating — the engineer's claim holds. Correctness of the retry/best-effort logic itself is the code-reviewer's call; from a design standpoint the "callers always get a `ParsedDocument`" contract (§5.1 downstream P5-03/04 dependency) is preserved.
- **Metadata annotation is additive, not a schema change.** `_annotate` adds `ocr_fallback_used`/`text_layer_usable`/`text_layer_reason`/`text_char_count` via `model_copy` into the free-form `metadata` dict — keeps `ParsedDocument`'s engine-agnostic shape (A2) while giving P5-04 observability. Acceptable; these are informational, not a new contract callers must branch on.
- **Follow-up (non-blocking, P5-04):** §5.1 specifies "OCR runs as a Celery background job … with progress surfaced to the UI." This task correctly stays synchronous (`asyncio.to_thread` to keep OCR off the event loop) and leaves Celery wiring to P5-04 — flagging only so the async-job requirement isn't forgotten when the endpoint lands.
- **Follow-up (non-blocking, P5-03/later):** OCR output sets `structured={}` and `markdown == text` (no layout recovery — expected for a plain-OCR tier). P5-03's LLM-assisted structuring must not assume rich `structured`/layout is present when the OCR fallback ran; `text_layer_usable`/`ocr_fallback_used` metadata is the signal to check. Design-consistent (§5.1 lists layout as a docling/PaddleOCR strength, not a Tesseract one).
