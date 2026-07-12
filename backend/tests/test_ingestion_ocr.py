"""Tests for the P5-02 OCR fallback: text-layer check, OCR parser, composite chain, VLM seam.

Three layers, mirroring the P5-01 test posture:

* **Pure/unit tests** drive the text-layer check, the OCR parser (through an **injected fake
  engine**), and the composite chain (through **fake parsers**). They need no OCR toolchain
  and run everywhere (including the CI curated venv, where Tesseract/OCRmyPDF are excluded).

* **One real end-to-end test** runs the *actual* Tesseract engine on an image rendered at
  test time. It is guarded by ``importorskip`` (pytesseract/PIL) plus a Tesseract-binary
  probe, so it skips cleanly where the toolchain isn't installed rather than erroring.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.ingestion import (
    CompositeDocumentParser,
    DocumentParseError,
    DocumentParser,
    OcrDocumentParser,
    ParsedDocument,
    ReservedVlmOcrParser,
    TextLayerCheck,
    UnsupportedDocumentError,
    build_default_composite_parser,
)


# --------------------------------------------------------------------------------------
# Helpers: a fake OCR engine and fake DocumentParsers (first-party shapes, kept local).
# --------------------------------------------------------------------------------------
class _FakeOcrEngine:
    """Records calls and returns a preconfigured text (or raises)."""

    def __init__(self, text: str = "OCR RECOVERED TEXT", *, error: Exception | None = None) -> None:
        self._text = text
        self._error = error
        self.calls: list[tuple[bytes, str]] = []

    def extract_text(self, source: bytes, *, source_format: str) -> str:
        self.calls.append((source, source_format))
        if self._error is not None:
            raise self._error
        return self._text


class _FakeParser(DocumentParser):
    """A DocumentParser returning a canned ParsedDocument (or raising), recording calls."""

    def __init__(
        self, result: ParsedDocument | None = None, *, error: Exception | None = None
    ) -> None:
        self._result = result
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def parse(
        self,
        source: Any,
        *,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> ParsedDocument:
        self.calls.append({"source": source, "filename": filename, "media_type": media_type})
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def _doc(text: str, *, page_count: int | None = None, fmt: str = "pdf") -> ParsedDocument:
    return ParsedDocument(
        markdown=text,
        text=text,
        source_format=fmt,
        page_count=page_count,
        metadata={"engine": "primary"},
    )


def _ocr_parser(engine: _FakeOcrEngine) -> OcrDocumentParser:
    return OcrDocumentParser(engine_factory=lambda: engine)


# --------------------------------------------------------------------------------------
# TextLayerCheck — the "usable text layer? → OCR?" decision, in isolation.
# --------------------------------------------------------------------------------------
def test_text_layer_empty_extract_is_not_usable() -> None:
    check = TextLayerCheck()
    assessment = check.assess(_doc("   \n\t "))
    assert assessment.has_usable_text is False
    assert assessment.char_count == 0


def test_text_layer_below_min_chars_is_not_usable() -> None:
    check = TextLayerCheck(min_chars=48)
    assessment = check.assess(_doc("a few chars"))  # 11 chars < 48
    assert assessment.has_usable_text is False
    assert assessment.char_count == 11


def test_text_layer_low_density_per_page_is_not_usable() -> None:
    # 60 chars over 10 pages = 6 chars/page — well under the density floor → OCR.
    check = TextLayerCheck(min_chars=48, min_chars_per_page=24.0)
    text = "x" * 60
    assessment = check.assess(_doc(text, page_count=10))
    assert assessment.has_usable_text is False
    assert assessment.chars_per_page == pytest.approx(6.0)


def test_text_layer_normal_document_is_usable() -> None:
    check = TextLayerCheck()
    text = "Jane Doe\nSenior Engineer\n" + ("Experience with FastAPI and Postgres. " * 20)
    assessment = check.assess(_doc(text, page_count=2))
    assert assessment.has_usable_text is True
    assert assessment.reason == "usable text layer"


def test_text_layer_pageless_document_skips_density_check() -> None:
    # DOCX has no page_count; a healthy char count is usable without a density check.
    check = TextLayerCheck()
    assessment = check.assess(_doc("A well-populated CV body. " * 10, page_count=None, fmt="docx"))
    assert assessment.has_usable_text is True
    assert assessment.chars_per_page is None


# --------------------------------------------------------------------------------------
# OcrDocumentParser — through an injected fake engine (no toolchain needed).
# --------------------------------------------------------------------------------------
def test_ocr_parser_is_a_document_parser() -> None:
    assert issubclass(OcrDocumentParser, DocumentParser)


def test_ocr_construction_does_not_build_engine() -> None:
    parser = OcrDocumentParser()
    assert parser._engine is None  # type: ignore[attr-defined]  # lazy-load contract


@pytest.mark.asyncio
async def test_ocr_parse_image_bytes_returns_parsed_document() -> None:
    engine = _FakeOcrEngine("Jane Doe — Engineer")
    parser = _ocr_parser(engine)

    parsed = await parser.parse(b"\x89PNG...", filename="scan.png")

    assert isinstance(parsed, ParsedDocument)
    assert parsed.text == "Jane Doe — Engineer"
    assert parsed.markdown == "Jane Doe — Engineer"  # OCR has no layout; markdown == text
    assert parsed.source_format == "png"
    assert parsed.metadata["engine"] == "ocr"
    assert parsed.metadata["filename"] == "scan.png"
    # Engine saw the raw bytes + detected format.
    assert engine.calls == [(b"\x89PNG...", "png")]


@pytest.mark.asyncio
async def test_ocr_parse_bytes_uses_media_type_when_no_extension() -> None:
    engine = _FakeOcrEngine("text")
    parser = _ocr_parser(engine)

    parsed = await parser.parse(b"data", media_type="image/jpeg")

    assert parsed.source_format == "jpg"
    assert engine.calls[0][1] == "jpg"


@pytest.mark.asyncio
async def test_ocr_parse_pdf_path_reads_file(tmp_path: Any) -> None:
    engine = _FakeOcrEngine("scanned pdf text")
    parser = _ocr_parser(engine)
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 scanned")

    parsed = await parser.parse(str(pdf), filename="resume.pdf")

    assert parsed.source_format == "pdf"
    assert engine.calls == [(b"%PDF-1.4 scanned", "pdf")]


@pytest.mark.asyncio
async def test_ocr_parse_without_hint_raises_unsupported() -> None:
    engine = _FakeOcrEngine()
    parser = _ocr_parser(engine)

    with pytest.raises(UnsupportedDocumentError):
        await parser.parse(b"data")
    assert engine.calls == []  # nothing handed to the engine


@pytest.mark.asyncio
async def test_ocr_parse_unsupported_format_raises_unsupported() -> None:
    engine = _FakeOcrEngine()
    parser = _ocr_parser(engine)

    # DOCX is a text format the OCR fallback deliberately does not render.
    with pytest.raises(UnsupportedDocumentError):
        await parser.parse(b"PK...", filename="cv.docx")
    assert engine.calls == []


@pytest.mark.asyncio
async def test_ocr_engine_exception_is_normalized() -> None:
    engine = _FakeOcrEngine(error=RuntimeError("tesseract exploded"))
    parser = _ocr_parser(engine)

    with pytest.raises(DocumentParseError) as excinfo:
        await parser.parse(b"data", filename="scan.png")
    assert "tesseract exploded" in str(excinfo.value)


# --------------------------------------------------------------------------------------
# CompositeDocumentParser — tiering: primary first, OCR only on no/low text layer.
# --------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_composite_uses_primary_when_text_layer_usable() -> None:
    good_text = "Jane Doe\n" + ("Experienced engineer. " * 30)
    primary = _FakeParser(_doc(good_text, page_count=1))
    ocr = _FakeParser(_doc("SHOULD NOT BE USED"))
    composite = CompositeDocumentParser(primary=primary, fallbacks=(ocr,))

    parsed = await composite.parse(b"data", filename="cv.pdf")

    assert parsed.text == good_text
    assert parsed.metadata["ocr_fallback_used"] is False
    assert parsed.metadata["text_layer_usable"] is True
    assert len(primary.calls) == 1
    assert ocr.calls == []  # fallback never triggered on a normal text document


@pytest.mark.asyncio
async def test_composite_falls_back_to_ocr_when_no_text_layer() -> None:
    primary = _FakeParser(_doc("   ", page_count=3))  # scanned PDF: no text layer
    ocr_text = "Jane Doe — recovered by OCR. " * 5
    ocr = _FakeParser(_doc(ocr_text, fmt="pdf"))
    composite = CompositeDocumentParser(primary=primary, fallbacks=(ocr,))

    parsed = await composite.parse(b"data", filename="scan.pdf")

    assert parsed.text == ocr_text
    assert parsed.metadata["ocr_fallback_used"] is True
    assert parsed.metadata["text_layer_usable"] is True
    assert len(ocr.calls) == 1
    # The same source/hints were forwarded to the fallback.
    assert ocr.calls[0]["filename"] == "scan.pdf"


@pytest.mark.asyncio
async def test_composite_returns_best_effort_when_all_tiers_empty() -> None:
    primary = _FakeParser(_doc("", page_count=2))
    ocr = _FakeParser(_doc("", fmt="pdf"))  # OCR also recovered nothing
    composite = CompositeDocumentParser(primary=primary, fallbacks=(ocr,))

    parsed = await composite.parse(b"data", filename="scan.pdf")

    assert isinstance(parsed, ParsedDocument)
    assert parsed.metadata["text_layer_usable"] is False
    assert len(ocr.calls) == 1  # fallback was attempted


@pytest.mark.asyncio
async def test_composite_degrades_gracefully_when_fallback_raises() -> None:
    primary = _FakeParser(_doc("", page_count=1))
    ocr = _FakeParser(error=DocumentParseError("OCR toolchain missing"))
    composite = CompositeDocumentParser(primary=primary, fallbacks=(ocr,))

    parsed = await composite.parse(b"data", filename="scan.pdf")

    # Falls through to the best-effort primary rather than propagating the OCR error.
    assert parsed.metadata["ocr_fallback_used"] is False
    assert parsed.metadata["text_layer_usable"] is False


@pytest.mark.asyncio
async def test_composite_keeps_richer_fallback_when_none_fully_usable() -> None:
    primary = _FakeParser(_doc("", page_count=2))
    ocr = _FakeParser(_doc("a bit", fmt="pdf"))  # some text, still under the usable floor
    composite = CompositeDocumentParser(primary=primary, fallbacks=(ocr,))

    parsed = await composite.parse(b"data", filename="scan.pdf")

    assert parsed.text == "a bit"  # the richer of the two extracts is kept
    assert parsed.metadata["text_layer_usable"] is False


def test_build_default_composite_parser_wires_docling_then_ocr() -> None:
    from app.ingestion.docling_parser import DoclingParser

    composite = build_default_composite_parser()
    assert isinstance(composite, CompositeDocumentParser)
    assert isinstance(composite._primary, DoclingParser)  # type: ignore[attr-defined]
    assert len(composite._fallbacks) == 1  # type: ignore[attr-defined]
    assert isinstance(composite._fallbacks[0], OcrDocumentParser)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------------------
# Reserved VLM-OCR seam — exists, conforms to the interface, not implemented.
# --------------------------------------------------------------------------------------
def test_reserved_vlm_parser_is_a_document_parser() -> None:
    assert issubclass(ReservedVlmOcrParser, DocumentParser)


@pytest.mark.asyncio
async def test_reserved_vlm_parser_raises_not_implemented() -> None:
    parser = ReservedVlmOcrParser()
    with pytest.raises(NotImplementedError):
        await parser.parse(b"data", filename="hard.pdf")


# --------------------------------------------------------------------------------------
# Real end-to-end: the actual Tesseract engine on an image rendered at test time.
# --------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_real_tesseract_ocr_reads_rendered_image() -> None:
    pytest.importorskip("pytesseract", reason="pytesseract not installed in this env")
    pil_image = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    pil_draw = pytest.importorskip("PIL.ImageDraw")
    pil_font = pytest.importorskip("PIL.ImageFont")

    import pytesseract

    try:
        pytesseract.get_tesseract_version()
    except Exception:  # pragma: no cover - env-dependent
        pytest.skip("tesseract binary not available")

    from io import BytesIO

    image = pil_image.new("RGB", (600, 140), color="white")
    draw = pil_draw.Draw(image)
    draw.text((20, 40), "Experience", fill="black", font=pil_font.load_default(size=64))
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    parser = OcrDocumentParser()  # real Tesseract engine
    parsed = await parser.parse(buffer.getvalue(), filename="rendered.png")

    assert parsed.source_format == "png"
    assert parsed.metadata["engine"] == "ocr"
    assert "experience" in parsed.text.lower()
