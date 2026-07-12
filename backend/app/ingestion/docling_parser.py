"""``DoclingParser`` — the primary ``DocumentParser`` engine, over IBM ``docling``.

Design ref: app-design-and-features.md §5.1 — docling is the **recommended primary**
engine (PDF/DOCX/PPTX/images → structured Markdown/JSON with layout, tables, reading
order, and built-in OCR backends in one MIT-licensed dependency).

**Why docling is imported lazily (never at module import / construction).** docling
pulls the heavy ML stack (``torch`` + layout/OCR models) and is deliberately **excluded**
from the backend CI curated install (see ``.github/workflows/backend-ci.yml``) — the same
posture ``SentenceTransformerEmbeddingClient`` takes for ``sentence-transformers``. So the
adapter defers ``import docling`` to the first :meth:`parse` call and builds the
``DocumentConverter`` lazily. Importing this module and constructing :class:`DoclingParser`
therefore need **no** ML stack and trigger **no** model download — so ``app.ingestion``
imports cleanly in CI, and only tests that actually convert a fixture require docling.

**The converter is behind an injectable seam** — the ``converter_factory`` constructor
arg: a zero-arg callable returning any object with a docling-``DocumentConverter``-compatible
``.convert(source)`` method. Production leaves it defaulted (lazily builds the real
converter); tests inject a small deterministic fake so no docling install/model is needed.

Non-goals (later P5 subtasks, kept out here so this stays the pure primary-engine wrapper):
OCR fallback selection (P5-02), LLM-assisted structured-profile parsing (P5-03), the
Celery ingestion task / upload endpoint (P5-04).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from io import BytesIO
from pathlib import PurePath
from typing import Any, BinaryIO

from app.ingestion.formats import extension_for_media_type
from app.ingestion.parser import (
    DocumentParseError,
    DocumentParser,
    UnsupportedDocumentError,
)
from app.ingestion.types import DocumentSource, ParsedDocument

#: A zero-arg factory returning a docling-``DocumentConverter``-compatible object — the
#: one exposing ``.convert(source) -> result``. Injecting one is the test seam; the
#: default builds the real converter lazily (see the module docstring).
ConverterFactory = Callable[[], Any]

#: A factory wrapping a ``bytes`` source into a docling ``DocumentStream``-compatible object
#: (one exposing ``.name`` and ``.stream``), given a format-detectable ``name`` and a binary
#: stream. Injecting one is the second test seam (mirroring :data:`ConverterFactory`) so the
#: bytes-wrapping logic is unit-testable without ``docling_core`` installed; the default
#: lazily imports the real ``DocumentStream`` (see the module docstring).
DocumentStreamFactory = Callable[[str, BinaryIO], Any]


class DoclingParser(DocumentParser):
    """:class:`DocumentParser` implemented over docling's ``DocumentConverter`` (§5.1).

    The converter is **lazy-loaded** on first use (never at construction) and the convert
    backend is injectable (:paramref:`converter_factory`) so CI/tests never install docling
    or download a model — see the module docstring.
    """

    def __init__(
        self,
        *,
        converter_factory: ConverterFactory | None = None,
        document_stream_factory: DocumentStreamFactory | None = None,
    ) -> None:
        """Construct the parser without importing docling or loading any model.

        Args:
            converter_factory: Zero-arg factory returning the convert backend (the
                injectable seam). ``None`` → the default lazily builds docling's
                ``DocumentConverter`` on first :meth:`parse` (``import docling`` is
                deferred to that call, so importing this module needs no ML stack).
            document_stream_factory: Factory wrapping a ``bytes`` source into a docling
                ``DocumentStream`` (the second injectable seam). ``None`` → the default
                lazily imports the real ``DocumentStream`` when wrapping bytes, so the
                import stays deferred and tests can verify the wrapping with a light fake.
        """
        self._converter_factory: ConverterFactory = (
            converter_factory or self._build_default_converter
        )
        self._document_stream_factory: DocumentStreamFactory = (
            document_stream_factory or self._build_default_document_stream
        )
        # Lazily populated on first parse; guarded so concurrent first-callers build once.
        self._converter: Any | None = None
        self._load_lock = asyncio.Lock()

    def _build_default_converter(self) -> Any:
        """Build the real docling converter. Imported here so docling is only needed on use."""
        from docling.document_converter import DocumentConverter  # noqa: PLC0415 - deferred

        return DocumentConverter()

    @staticmethod
    def _build_default_document_stream(name: str, stream: BinaryIO) -> Any:
        """Wrap bytes in a real docling ``DocumentStream`` (imported here to keep it deferred)."""
        from docling_core.types.io import DocumentStream  # noqa: PLC0415 - deferred

        return DocumentStream(name=name, stream=stream)

    async def _get_converter(self) -> Any:
        """Return the convert backend, building it once on first call (off the event loop)."""
        if self._converter is None:
            async with self._load_lock:
                if self._converter is None:
                    # Converter construction is heavy/blocking — keep it off the loop.
                    self._converter = await asyncio.to_thread(self._converter_factory)
        return self._converter

    async def parse(
        self,
        source: DocumentSource,
        *,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> ParsedDocument:
        converter = await self._get_converter()
        convert_source = self._build_convert_source(source, filename, media_type)
        try:
            # docling's convert is CPU-bound (layout/OCR); run it off the event loop.
            result = await asyncio.to_thread(converter.convert, convert_source)
        except UnsupportedDocumentError:
            raise
        except Exception as exc:  # docling raises assorted engine errors — normalize them.
            raise DocumentParseError(f"docling failed to parse the document: {exc}") from exc
        return self._to_parsed_document(result, filename)

    def _build_convert_source(
        self,
        source: DocumentSource,
        filename: str | None,
        media_type: str | None,
    ) -> Any:
        """Turn the caller's ``source`` into what docling's ``convert`` accepts.

        Path sources pass through as-is (docling detects format from the path name).
        ``bytes`` sources are wrapped in a docling ``DocumentStream`` with a name that
        carries a format-detectable extension (from ``filename`` or ``media_type``).
        """
        if isinstance(source, bytes):
            name = self._stream_name(filename, media_type)
            return self._document_stream_factory(name, BytesIO(source))
        return source

    @staticmethod
    def _stream_name(filename: str | None, media_type: str | None) -> str:
        """Derive a format-detectable stream name for a ``bytes`` source.

        Prefers ``filename`` when it has an extension; otherwise appends the extension
        mapped from ``media_type``. Raises :class:`UnsupportedDocumentError` when neither
        yields an extension — docling cannot detect a format without one.
        """
        if filename and PurePath(filename).suffix:
            return filename
        extension = extension_for_media_type(media_type)
        if extension is None:
            raise UnsupportedDocumentError(
                "bytes source needs a 'filename' with an extension or a known "
                f"'media_type' to detect the document format (got filename={filename!r}, "
                f"media_type={media_type!r})"
            )
        stem = PurePath(filename).stem if filename else "document"
        return f"{stem}{extension}"

    @staticmethod
    def _to_parsed_document(result: Any, filename: str | None) -> ParsedDocument:
        """Translate docling's ``ConversionResult`` into a :class:`ParsedDocument`.

        Rejects failed conversions (raising :class:`DocumentParseError`); a
        ``PARTIAL_SUCCESS`` is accepted (some pages recovered) since downstream OCR can
        still improve on a partial extract.
        """
        status = getattr(result, "status", None)
        status_name = getattr(status, "name", str(status))
        if status_name not in {"SUCCESS", "PARTIAL_SUCCESS"}:
            raise DocumentParseError(f"docling conversion did not succeed (status={status_name})")

        document = result.document
        source_format = _format_name(result)
        page_count = getattr(getattr(result, "input", None), "page_count", 0) or 0
        metadata: dict[str, Any] = {"status": status_name}
        if filename:
            metadata["filename"] = filename

        return ParsedDocument(
            markdown=document.export_to_markdown(),
            text=document.export_to_text(),
            structured=document.export_to_dict(),
            source_format=source_format,
            page_count=page_count if page_count > 0 else None,
            metadata=metadata,
        )


def _format_name(result: Any) -> str:
    """Extract the lower-cased detected format (e.g. ``"docx"``) from a docling result."""
    fmt = getattr(getattr(result, "input", None), "format", None)
    value = getattr(fmt, "value", None)
    if isinstance(value, str):
        return value.lower()
    return str(value).lower() if value is not None else "unknown"
