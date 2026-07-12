"""Tests for the ``DocumentParser`` interface + ``DoclingParser`` (P5-01).

Two layers:

* **Interface/adapter tests** drive :class:`DoclingParser` through an **injected fake
  converter** that mimics docling's ``ConversionResult`` shape. They need no docling
  install and run everywhere (including the CI curated venv, where docling is excluded),
  covering source handling (path vs. bytes), format-hint derivation, status/error
  normalization, and the ``ConversionResult`` → :class:`ParsedDocument` mapping.

* **One real end-to-end test** runs the *actual* docling engine on a committed DOCX
  fixture (DOCX parsing uses docling's simple pipeline — no model download, offline-safe).
  It is guarded by ``importorskip("docling")`` so it skips cleanly where docling isn't
  installed rather than erroring collection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.ingestion import (
    DoclingParser,
    DocumentParseError,
    DocumentParser,
    ParsedDocument,
    UnsupportedDocumentError,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ingestion"


# --------------------------------------------------------------------------------------
# Fakes mimicking docling's ConversionResult shape (an external SDK shape, so kept local
# to this test rather than in the first-party tests/fakes.py).
# --------------------------------------------------------------------------------------
class _FakeStatus:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeFormat:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeInput:
    def __init__(self, fmt: str, page_count: int) -> None:
        self.format = _FakeFormat(fmt)
        self.page_count = page_count


class _FakeDocument:
    def __init__(self, markdown: str, text: str, structured: dict[str, Any]) -> None:
        self._markdown = markdown
        self._text = text
        self._structured = structured

    def export_to_markdown(self) -> str:
        return self._markdown

    def export_to_text(self) -> str:
        return self._text

    def export_to_dict(self) -> dict[str, Any]:
        return self._structured


class _FakeResult:
    def __init__(
        self,
        *,
        status: str = "SUCCESS",
        fmt: str = "DOCX",
        page_count: int = 0,
        markdown: str = "## Jane Doe",
        text: str = "Jane Doe",
        structured: dict[str, Any] | None = None,
    ) -> None:
        self.status = _FakeStatus(status)
        self.input = _FakeInput(fmt, page_count)
        self.document = _FakeDocument(markdown, text, structured or {"name": "doc"})


class _FakeConverter:
    """Records the source it was handed and returns a preconfigured result."""

    def __init__(
        self, result: _FakeResult | None = None, *, error: Exception | None = None
    ) -> None:
        self._result = result or _FakeResult()
        self._error = error
        self.calls: list[Any] = []

    def convert(self, source: Any) -> _FakeResult:
        self.calls.append(source)
        if self._error is not None:
            raise self._error
        return self._result


class _FakeDocumentStream:
    """Light stand-in for docling's ``DocumentStream`` (``.name`` + ``.stream``).

    Injected via the ``document_stream_factory`` seam so the bytes-wrapping logic is
    exercised without ``docling_core`` installed (the curated CI venv excludes docling).
    """

    def __init__(self, name: str, stream: Any) -> None:
        self.name = name
        self.stream = stream


def _parser(result: _FakeResult | None = None, *, error: Exception | None = None) -> DoclingParser:
    converter = _FakeConverter(result, error=error)
    parser = DoclingParser(
        converter_factory=lambda: converter,
        document_stream_factory=_FakeDocumentStream,
    )
    parser._test_converter = converter  # type: ignore[attr-defined]  # convenience handle
    return parser


# --------------------------------------------------------------------------------------
# Interface / contract
# --------------------------------------------------------------------------------------
def test_docling_parser_is_a_document_parser() -> None:
    assert issubclass(DoclingParser, DocumentParser)


def test_construction_does_not_import_docling_or_build_converter() -> None:
    # Default factory must not be invoked at construction (lazy-load contract).
    parser = DoclingParser()
    assert parser._converter is None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_parse_path_source_maps_result_fields() -> None:
    result = _FakeResult(
        fmt="DOCX",
        markdown="## Jane Doe\n\nEngineer",
        text="Jane Doe\nEngineer",
        structured={"name": "cv", "elements": []},
    )
    parser = _parser(result)

    parsed = await parser.parse("/tmp/cv.docx", filename="cv.docx")

    assert isinstance(parsed, ParsedDocument)
    assert parsed.markdown == "## Jane Doe\n\nEngineer"
    assert parsed.text == "Jane Doe\nEngineer"
    assert parsed.structured == {"name": "cv", "elements": []}
    assert parsed.source_format == "docx"
    assert parsed.metadata["filename"] == "cv.docx"
    assert parsed.metadata["status"] == "SUCCESS"
    # A path source passes straight through to docling.
    assert parser._test_converter.calls == ["/tmp/cv.docx"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_parse_bytes_source_wraps_in_document_stream_with_filename() -> None:
    parser = _parser()

    await parser.parse(b"%PDF-1.4 ...", filename="resume.pdf")

    (source,) = parser._test_converter.calls  # type: ignore[attr-defined]
    # docling's DocumentStream (duck-typed): carries the name we derived + a stream.
    assert source.name == "resume.pdf"
    assert source.stream.read() == b"%PDF-1.4 ..."


@pytest.mark.asyncio
async def test_parse_bytes_derives_extension_from_media_type() -> None:
    parser = _parser()

    await parser.parse(b"data", media_type="application/pdf")

    (source,) = parser._test_converter.calls  # type: ignore[attr-defined]
    assert source.name.endswith(".pdf")


@pytest.mark.asyncio
async def test_parse_bytes_without_hint_raises_unsupported() -> None:
    parser = _parser()

    with pytest.raises(UnsupportedDocumentError):
        await parser.parse(b"data")

    # Nothing should have been handed to docling.
    assert parser._test_converter.calls == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_parse_bytes_unknown_media_type_raises_unsupported() -> None:
    parser = _parser()

    with pytest.raises(UnsupportedDocumentError):
        await parser.parse(b"data", media_type="application/x-unknown")


@pytest.mark.asyncio
async def test_failed_status_raises_document_parse_error() -> None:
    parser = _parser(_FakeResult(status="FAILURE"))

    with pytest.raises(DocumentParseError):
        await parser.parse("/tmp/broken.pdf", filename="broken.pdf")


@pytest.mark.asyncio
async def test_partial_success_is_accepted() -> None:
    parser = _parser(_FakeResult(status="PARTIAL_SUCCESS", text="partial"))

    parsed = await parser.parse("/tmp/cv.pdf", filename="cv.pdf")

    assert parsed.text == "partial"
    assert parsed.metadata["status"] == "PARTIAL_SUCCESS"


@pytest.mark.asyncio
async def test_engine_exception_is_normalized_to_document_parse_error() -> None:
    parser = _parser(error=RuntimeError("boom deep in docling"))

    with pytest.raises(DocumentParseError) as excinfo:
        await parser.parse("/tmp/cv.pdf", filename="cv.pdf")

    assert "boom deep in docling" in str(excinfo.value)


@pytest.mark.asyncio
async def test_page_count_reported_when_present_else_none() -> None:
    with_pages = _parser(_FakeResult(fmt="PDF", page_count=3))
    parsed = await with_pages.parse("/tmp/cv.pdf", filename="cv.pdf")
    assert parsed.page_count == 3

    no_pages = _parser(_FakeResult(fmt="DOCX", page_count=0))
    parsed = await no_pages.parse("/tmp/cv.docx", filename="cv.docx")
    assert parsed.page_count is None


@pytest.mark.asyncio
async def test_is_empty_reflects_recovered_text() -> None:
    empty = _parser(_FakeResult(text="   \n  "))
    parsed = await empty.parse("/tmp/scan.pdf", filename="scan.pdf")
    assert parsed.is_empty is True

    nonempty = _parser(_FakeResult(text="Jane Doe"))
    parsed = await nonempty.parse("/tmp/cv.docx", filename="cv.docx")
    assert parsed.is_empty is False


# --------------------------------------------------------------------------------------
# Real end-to-end: actual docling engine on a committed DOCX fixture.
# --------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_real_docling_parses_docx_fixture() -> None:
    pytest.importorskip("docling", reason="docling (heavy ML dep) not installed in this env")

    fixture = FIXTURES / "sample_cv.docx"
    assert fixture.exists(), "DOCX fixture missing"

    parser = DoclingParser()  # real converter, no download needed for DOCX
    parsed = await parser.parse(str(fixture), filename="sample_cv.docx")

    assert parsed.source_format == "docx"
    assert parsed.is_empty is False
    # Layout-aware Markdown recovered the headings + content.
    assert "Jane Doe" in parsed.markdown
    assert "Experience" in parsed.markdown
    assert "FastAPI" in parsed.text
    # Structured JSON export is a non-empty mapping.
    assert isinstance(parsed.structured, dict)
    assert parsed.structured


@pytest.mark.asyncio
async def test_real_docling_parses_docx_from_bytes() -> None:
    pytest.importorskip("docling", reason="docling (heavy ML dep) not installed in this env")

    data = (FIXTURES / "sample_cv.docx").read_bytes()

    parser = DoclingParser()
    parsed = await parser.parse(data, filename="sample_cv.docx")

    assert parsed.source_format == "docx"
    assert "Jane Doe" in parsed.markdown
