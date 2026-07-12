"""Reserved seam for the VLM-OCR last-resort tier (NOT implemented in P5-02).

Design ref: app-design-and-features.md §5.1 engine tiering — the bottom tier is
*"OCR via a vision-language model … robust on messy slide-style CVs; can parse directly to
JSON; higher latency/cost; good last-resort for hard docs"*, reserved for documents that
fail structured extraction even after the Tesseract/OCRmyPDF fallback.

This module makes that tier a **first-class, importable extension point** without wiring an
actual VLM call (out of scope per the P5-02 task). :class:`ReservedVlmOcrParser` already
conforms to the :class:`DocumentParser` interface, so enabling the tier later is purely
additive: implement :meth:`~ReservedVlmOcrParser.parse` (call the HF VLM, map its output to
:class:`ParsedDocument`) and append an instance to the composite's fallback chain —

    CompositeDocumentParser(
        primary=DoclingParser(),
        fallbacks=(OcrDocumentParser(), VlmOcrParser(...)),  # VLM after Tesseract
    )

No caller, service, or agent changes are needed — the interface and the ordered-fallback
chain (:class:`~app.ingestion.composite_parser.CompositeDocumentParser`) are the seam.
"""

from __future__ import annotations

from app.ingestion.parser import DocumentParser
from app.ingestion.types import DocumentSource, ParsedDocument


class ReservedVlmOcrParser(DocumentParser):
    """Placeholder for the §5.1 VLM-OCR last-resort tier — intentionally not implemented.

    Exists so the tier is a real, typed extension point (interfaces-before-implementations):
    it *is* a :class:`DocumentParser`, so it drops into the composite fallback chain the day
    a VLM is wired. Until then :meth:`parse` raises :class:`NotImplementedError` — it must
    never be added to a live chain in P5-02.
    """

    async def parse(
        self,
        source: DocumentSource,
        *,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> ParsedDocument:
        raise NotImplementedError(
            "VLM-OCR tier is reserved (design §5.1) but not implemented in P5-02. "
            "Wire a vision-language model here and append this parser to the composite's "
            "fallback chain to enable the last-resort tier."
        )
