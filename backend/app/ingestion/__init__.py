"""Document ingestion — the ``DocumentParser`` interface + a tiered engine chain.

P5-01 shipped the engine-agnostic seam (design §5.1): callers depend on
:class:`~app.ingestion.parser.DocumentParser` (an ABC), with
:class:`~app.ingestion.docling_parser.DoclingParser` as the primary docling-backed engine.

P5-02 adds the OCR fallback tier and the orchestration that chooses between engines:

* :class:`~app.ingestion.text_layer.TextLayerCheck` — the "usable text layer? → OCR?"
  decision, keyed off :attr:`~app.ingestion.types.ParsedDocument.is_empty` + text density.
* :class:`~app.ingestion.ocr_parser.OcrDocumentParser` — a Tesseract/OCRmyPDF-backed
  :class:`DocumentParser` for scanned/image CVs.
* :class:`~app.ingestion.composite_parser.CompositeDocumentParser` — tries the primary,
  falls back to OCR only on a no/low-text verdict, and exposes the single interface callers
  depend on. :func:`~app.ingestion.composite_parser.build_default_composite_parser` wires the
  production chain.
* :class:`~app.ingestion.vlm.ReservedVlmOcrParser` — a documented, not-yet-implemented seam
  for the §5.1 VLM last-resort tier (P5-03 structuring and P5-04 endpoint/Celery come later).

All heavy toolchains (docling's ML stack, the Tesseract/OCRmyPDF binaries) are imported
lazily inside their adapters (never at import), so this package imports cleanly even where
they are not installed (e.g. CI).
"""

from app.ingestion.composite_parser import (
    CompositeDocumentParser,
    build_default_composite_parser,
)
from app.ingestion.docling_parser import ConverterFactory, DoclingParser
from app.ingestion.formats import detect_format
from app.ingestion.ocr_parser import (
    OcrDocumentParser,
    OcrEngine,
    OcrEngineFactory,
    TesseractOcrEngine,
)
from app.ingestion.parser import (
    DocumentParseError,
    DocumentParser,
    UnsupportedDocumentError,
)
from app.ingestion.profile import (
    EducationItem,
    ExperienceItem,
    ProfileSchema,
    ProfileStructuringError,
)
from app.ingestion.structuring import (
    PROFILE_TOOL_NAME,
    PROFILE_TOOL_SCHEMA,
    ProfileStructurer,
)
from app.ingestion.text_layer import TextLayerAssessment, TextLayerCheck
from app.ingestion.types import DocumentSource, ParsedDocument
from app.ingestion.vlm import ReservedVlmOcrParser

__all__ = [
    "PROFILE_TOOL_NAME",
    "PROFILE_TOOL_SCHEMA",
    "CompositeDocumentParser",
    "ConverterFactory",
    "DoclingParser",
    "DocumentParseError",
    "DocumentParser",
    "DocumentSource",
    "EducationItem",
    "ExperienceItem",
    "OcrDocumentParser",
    "OcrEngine",
    "OcrEngineFactory",
    "ParsedDocument",
    "ProfileSchema",
    "ProfileStructurer",
    "ProfileStructuringError",
    "ReservedVlmOcrParser",
    "TesseractOcrEngine",
    "TextLayerAssessment",
    "TextLayerCheck",
    "UnsupportedDocumentError",
    "build_default_composite_parser",
    "detect_format",
]
