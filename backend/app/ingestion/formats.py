"""Shared format-detection vocabulary for the ingestion engines.

Both the primary :class:`~app.ingestion.docling_parser.DoclingParser` (to build a
format-detectable stream name for ``bytes`` sources) and the OCR fallback
:class:`~app.ingestion.ocr_parser.OcrDocumentParser` (to route a source to the image vs.
PDF OCR path) need the same "what format is this?" logic. Keeping it here — one map, one
detector — avoids the two engines drifting apart (DRY).

Design ref: app-design-and-features.md §5.1 (the §5.1 CV formats: PDF/DOCX/PPTX/images).
"""

from __future__ import annotations

from pathlib import PurePath

#: MIME type → filename extension (with leading dot). Used as a *fallback* format hint for
#: ``bytes`` sources whose ``filename`` carries no usable extension. Covers the §5.1 CV
#: formats (PDF/DOCX/PPTX + the common raster image types OCR handles).
MEDIA_TYPE_EXTENSIONS: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/tiff": ".tiff",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
}


def extension_for_media_type(media_type: str | None) -> str | None:
    """Return the ``.ext`` mapped from ``media_type`` (with leading dot), or ``None``."""
    return MEDIA_TYPE_EXTENSIONS.get((media_type or "").lower())


def detect_format(*, filename: str | None = None, media_type: str | None = None) -> str | None:
    """Best-effort lower-cased format token (no leading dot) for a source, e.g. ``"pdf"``.

    Prefers the ``filename`` extension (the most reliable signal a caller can give);
    falls back to the extension mapped from ``media_type``. Returns ``None`` when neither
    yields a format — callers raise :class:`~app.ingestion.parser.UnsupportedDocumentError`.
    """
    if filename:
        suffix = PurePath(filename).suffix.lower().lstrip(".")
        if suffix:
            return suffix
    extension = extension_for_media_type(media_type)
    if extension is not None:
        return extension.lstrip(".").lower()
    return None
