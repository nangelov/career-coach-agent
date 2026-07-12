"""``OcrDocumentParser`` — the OCR fallback ``DocumentParser`` engine.

Design ref: app-design-and-features.md §5.1 — the light **Tesseract (`pytesseract`) +
OCRmyPDF** fallback for scanned/image/slide-style CVs where the primary docling pass
recovered little/no text. It implements the **same** :class:`DocumentParser` interface as
:class:`~app.ingestion.docling_parser.DoclingParser` (no new parallel abstraction), so the
composing parser (:mod:`app.ingestion.composite_parser`) can swap it in transparently.

**Why the OCR toolchain is imported lazily (never at module import / construction).**
``pytesseract`` needs the Tesseract binary and ``ocrmypdf`` pulls Ghostscript/qpdf — none
of which belong in the curated CI venv (same posture the docling adapter takes for its ML
stack). So imports are deferred to the first :meth:`parse` call. Importing this module and
constructing :class:`OcrDocumentParser` therefore need **no** OCR toolchain — the package
imports cleanly in CI, and only tests that actually OCR a fixture require the binaries.

**The OCR engine is behind an injectable seam** — the ``engine_factory`` constructor arg:
a zero-arg callable returning any object satisfying :class:`OcrEngine`. Production leaves it
defaulted (lazily builds the real Tesseract/OCRmyPDF engine); tests inject a deterministic
fake so no binary is needed.

Scope: raster **images** (PNG/JPEG/TIFF/BMP/WebP) via Tesseract and **PDF** via OCRmyPDF —
the formats a "no text layer" fallback actually applies to. Office formats (DOCX/PPTX) are
not OCR-rendered here (they need a headless renderer); the reserved VLM-OCR tier
(:mod:`app.ingestion.vlm`) is where harder slide-style documents go later.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.ingestion.formats import detect_format
from app.ingestion.parser import (
    DocumentParseError,
    DocumentParser,
    UnsupportedDocumentError,
)
from app.ingestion.types import DocumentSource, ParsedDocument

#: Formats the OCR fallback can actually process (lower-cased, no leading dot). PDFs go
#: through OCRmyPDF; the rest are raster images Tesseract reads directly.
_PDF_FORMAT = "pdf"
_IMAGE_FORMATS: frozenset[str] = frozenset({"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"})
_SUPPORTED_FORMATS: frozenset[str] = _IMAGE_FORMATS | {_PDF_FORMAT}


@runtime_checkable
class OcrEngine(Protocol):
    """The OCR backend seam: raw bytes of one supported format → recovered plain text.

    Implementations own the binaries (Tesseract for images, OCRmyPDF for PDFs). Kept to a
    single method so a test fake is trivial and the parser stays engine-agnostic.
    """

    def extract_text(self, source: bytes, *, source_format: str) -> str:
        """Return the OCR-recovered text for ``source`` (of ``source_format``)."""
        ...


#: Zero-arg factory returning an :class:`OcrEngine`. The injection seam (tests pass a fake);
#: the default lazily builds :class:`TesseractOcrEngine` on first parse.
OcrEngineFactory = Callable[[], OcrEngine]


class TesseractOcrEngine:
    """Default :class:`OcrEngine` — Tesseract for images, OCRmyPDF for PDFs.

    All heavy imports (``pytesseract``, ``PIL``, ``ocrmypdf``) are deferred into the methods
    that use them so importing/constructing this class needs no OCR toolchain (see the
    module docstring).
    """

    def extract_text(self, source: bytes, *, source_format: str) -> str:
        if source_format == _PDF_FORMAT:
            return self._ocr_pdf(source)
        return self._ocr_image(source)

    @staticmethod
    def _ocr_image(data: bytes) -> str:
        """OCR a raster image with Tesseract via ``pytesseract``."""
        from io import BytesIO

        import pytesseract  # noqa: PLC0415 - deferred: needs the Tesseract binary
        from PIL import Image  # noqa: PLC0415 - deferred

        with Image.open(BytesIO(data)) as image:
            return str(pytesseract.image_to_string(image))

    @staticmethod
    def _ocr_pdf(data: bytes) -> str:
        """Add a text layer to a scanned PDF with OCRmyPDF and return the sidecar text."""
        import tempfile  # noqa: PLC0415 - deferred (only PDF OCR needs temp files)

        import ocrmypdf  # noqa: PLC0415 - deferred: pulls Ghostscript/qpdf/Tesseract

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            input_pdf = tmp_dir / "input.pdf"
            output_pdf = tmp_dir / "output.pdf"
            sidecar = tmp_dir / "output.txt"
            input_pdf.write_bytes(data)
            # force_ocr: the fallback only runs when the text layer is missing/unusable, so
            # rasterize+OCR every page. sidecar: OCRmyPDF writes recovered text alongside the
            # searchable PDF, which is all we need here. progress_bar off (background job).
            ocrmypdf.ocr(
                input_pdf,
                output_pdf,
                sidecar=sidecar,
                force_ocr=True,
                progress_bar=False,
            )
            return sidecar.read_text(encoding="utf-8")


class OcrDocumentParser(DocumentParser):
    """:class:`DocumentParser` backed by an OCR engine — the §5.1 scanned/image fallback.

    The OCR engine is lazy-loaded on first use (never at construction) and injectable
    (:paramref:`engine_factory`) so CI/tests never install the OCR toolchain — see the
    module docstring.
    """

    def __init__(self, *, engine_factory: OcrEngineFactory | None = None) -> None:
        """Construct the parser without importing any OCR library or binary.

        Args:
            engine_factory: Zero-arg factory returning the :class:`OcrEngine` backend (the
                injectable seam). ``None`` → the default lazily builds
                :class:`TesseractOcrEngine` on first :meth:`parse`.
        """
        self._engine_factory: OcrEngineFactory = engine_factory or TesseractOcrEngine
        # Lazily populated on first parse; guarded so concurrent first-callers build once.
        self._engine: OcrEngine | None = None
        self._load_lock = asyncio.Lock()

    async def _get_engine(self) -> OcrEngine:
        """Return the OCR engine, building it once on first call (off the event loop)."""
        if self._engine is None:
            async with self._load_lock:
                if self._engine is None:
                    self._engine = await asyncio.to_thread(self._engine_factory)
        return self._engine

    async def parse(
        self,
        source: DocumentSource,
        *,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> ParsedDocument:
        data, source_format = self._read_source(source, filename, media_type)
        engine = await self._get_engine()
        try:
            # OCR is CPU-bound (rasterize + recognition); keep it off the event loop.
            text = await asyncio.to_thread(engine.extract_text, data, source_format=source_format)
        except Exception as exc:  # normalize any engine/binary failure to our error type.
            raise DocumentParseError(f"OCR failed to parse the document: {exc}") from exc

        metadata: dict[str, Any] = {"engine": "ocr", "source_format": source_format}
        if filename:
            metadata["filename"] = filename
        # OCR recovers plain text without layout; markdown mirrors text (no structure to add).
        return ParsedDocument(
            markdown=text,
            text=text,
            structured={},
            source_format=source_format,
            page_count=None,
            metadata=metadata,
        )

    @staticmethod
    def _read_source(
        source: DocumentSource,
        filename: str | None,
        media_type: str | None,
    ) -> tuple[bytes, str]:
        """Normalize ``source`` to raw bytes + a supported OCR format token.

        Path sources are read from disk (their name supplies the format); ``bytes`` sources
        take their format from ``filename``/``media_type``. Raises
        :class:`UnsupportedDocumentError` when the format cannot be determined or is not one
        the OCR engine can process.
        """
        if isinstance(source, bytes):
            data = source
            fmt = detect_format(filename=filename, media_type=media_type)
        else:
            path = Path(source)
            data = path.read_bytes()
            fmt = detect_format(filename=path.name, media_type=media_type)

        if fmt is None:
            raise UnsupportedDocumentError(
                "OCR needs a 'filename' with an extension or a known 'media_type' to "
                f"detect the document format (got filename={filename!r}, "
                f"media_type={media_type!r})"
            )
        if fmt not in _SUPPORTED_FORMATS:
            raise UnsupportedDocumentError(
                f"OCR fallback does not support format {fmt!r}; supported: "
                f"{sorted(_SUPPORTED_FORMATS)}"
            )
        return data, fmt
