"""``CompositeDocumentParser`` — the tiered ingestion chain (primary → OCR → …).

Design ref: app-design-and-features.md §5.1 pipeline & tiering — docling primary, with the
Tesseract/OCRmyPDF OCR fallback for scanned/image CVs, and a reserved VLM last-resort tier.
This parser orchestrates that chain behind the **single** :class:`DocumentParser` interface,
so callers (P5-03 structuring, the P5-04 upload endpoint / Celery task) never learn which
engine ultimately ran — they get a :class:`ParsedDocument` either way.

How the tiering decision is made — and *why here* rather than reinventing detection: the
composite runs the primary engine, then asks :class:`TextLayerCheck` whether the result has
a usable text layer (keyed off :attr:`ParsedDocument.is_empty` + density, per the P5-01
architecture-review note). Only on a "no/low usable text" verdict does it walk the ordered
``fallbacks`` (OCR today; VLM tomorrow — see :mod:`app.ingestion.vlm`), returning the first
tier that yields usable text. If no tier improves on the primary, it returns the best-effort
extract so callers always get *something* to work with.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.ingestion.docling_parser import DoclingParser
from app.ingestion.ocr_parser import OcrDocumentParser
from app.ingestion.parser import DocumentParseError, DocumentParser
from app.ingestion.text_layer import TextLayerAssessment, TextLayerCheck
from app.ingestion.types import DocumentSource, ParsedDocument


class CompositeDocumentParser(DocumentParser):
    """Tiered :class:`DocumentParser`: primary engine, OCR fallback on no/low text layer.

    Args:
        primary: The first-choice engine (production: :class:`DoclingParser`).
        fallbacks: Ordered lower tiers tried, in order, only when the current best result
            has no usable text layer (production: ``(OcrDocumentParser(),)``; a VLM tier can
            be appended later — see :mod:`app.ingestion.vlm`).
        text_layer_check: The usable-text-layer decision. Defaults to a
            :class:`TextLayerCheck` with conservative thresholds.
    """

    def __init__(
        self,
        *,
        primary: DocumentParser,
        fallbacks: Sequence[DocumentParser],
        text_layer_check: TextLayerCheck | None = None,
    ) -> None:
        self._primary = primary
        self._fallbacks: tuple[DocumentParser, ...] = tuple(fallbacks)
        self._check = text_layer_check or TextLayerCheck()

    async def parse(
        self,
        source: DocumentSource,
        *,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> ParsedDocument:
        best = await self._primary.parse(source, filename=filename, media_type=media_type)
        best_assessment = self._check.assess(best)
        if best_assessment.has_usable_text:
            return self._annotate(best, fallback_used=False, assessment=best_assessment)

        best_fallback_used = False
        for tier in self._fallbacks:
            try:
                candidate = await tier.parse(source, filename=filename, media_type=media_type)
            except DocumentParseError:
                # This tier can't handle the source (e.g. OCR on an unsupported format) or
                # failed outright — degrade gracefully to the next tier / best-effort.
                continue
            assessment = self._check.assess(candidate)
            if assessment.has_usable_text:
                return self._annotate(candidate, fallback_used=True, assessment=assessment)
            # Keep the candidate only if it recovered more text than the current best.
            if assessment.char_count > best_assessment.char_count:
                best, best_assessment, best_fallback_used = candidate, assessment, True

        # No tier produced a usable text layer — return the best effort we have.
        return self._annotate(best, fallback_used=best_fallback_used, assessment=best_assessment)

    @staticmethod
    def _annotate(
        document: ParsedDocument,
        *,
        fallback_used: bool,
        assessment: TextLayerAssessment,
    ) -> ParsedDocument:
        """Return a copy of ``document`` with the tiering decision recorded in metadata.

        Lets downstream steps (and debugging) see whether OCR ran and why, without changing
        the engine-agnostic :class:`ParsedDocument` shape. All values stay JSON-serializable.
        """
        metadata: dict[str, Any] = {
            **document.metadata,
            "ocr_fallback_used": fallback_used,
            "text_layer_usable": assessment.has_usable_text,
            "text_layer_reason": assessment.reason,
            "text_char_count": assessment.char_count,
        }
        return document.model_copy(update={"metadata": metadata})


def build_default_composite_parser() -> CompositeDocumentParser:
    """Wire the production ingestion chain: docling primary → Tesseract/OCRmyPDF fallback.

    A convenience for the P5-04 wiring (endpoint / Celery task) and manual use; keeps the
    tier composition in one place. Construction stays cheap — neither engine imports its
    heavy toolchain until the first :meth:`~CompositeDocumentParser.parse`.
    """
    return CompositeDocumentParser(
        primary=DoclingParser(),
        fallbacks=(OcrDocumentParser(),),
    )
