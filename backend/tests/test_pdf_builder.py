"""Unit tests for the PDP PDF builder + validation gate (P7-02, design §5.2 / §5.7).

No I/O and no reportlab visual inspection: the render smoke test asserts non-empty ``%PDF``
bytes come back without reportlab raising, and the gate tests exercise the v1 length / section
thresholds over the structured :class:`~app.schemas.pdp.PdpContent`.
"""

from __future__ import annotations

from app.pdf import (
    MIN_PDP_CHARS,
    MIN_REQUIRED_SECTIONS,
    build_pdp_pdf,
    validate_pdp_content,
)
from app.pdf.builder import _inline
from app.schemas.pdp import SECTION_HEADINGS, LearningResourceRef, PdpContent


def _full_content(**overrides: object) -> PdpContent:
    """A representative six-section plan comfortably past both gate thresholds."""
    body = "This section has a substantial, non-trivial body of guidance for the plan. " * 3
    fields = {field: body for field, _ in SECTION_HEADINGS}
    fields.update(overrides)
    return PdpContent(**fields)  # type: ignore[arg-type]


# --- validation gate --------------------------------------------------------------------


def test_validate_passes_for_full_plan() -> None:
    assert validate_pdp_content(_full_content()) is True


def test_validate_rejects_short_plan() -> None:
    # All six sections present but only a few chars total — under MIN_PDP_CHARS.
    content = _full_content(**{field: "x" for field, _ in SECTION_HEADINGS})
    assert sum(len(getattr(content, f)) for f, _ in SECTION_HEADINGS) < MIN_PDP_CHARS
    assert validate_pdp_content(content) is False


def test_validate_rejects_too_few_sections() -> None:
    # One very long section clears the 500-char bar, but the other five are empty, so
    # fewer than MIN_REQUIRED_SECTIONS have a non-trivial body.
    empty = {field: "" for field, _ in SECTION_HEADINGS}
    empty["current_skills_assessment"] = "y" * (MIN_PDP_CHARS + 50)
    content = PdpContent(**empty)  # type: ignore[arg-type]
    assert validate_pdp_content(content) is False


def test_validate_passes_at_exactly_four_sections() -> None:
    fields = {field: "" for field, _ in SECTION_HEADINGS}
    long_body = "z" * 200
    for field, _ in SECTION_HEADINGS[:MIN_REQUIRED_SECTIONS]:
        fields[field] = long_body
    content = PdpContent(**fields)  # type: ignore[arg-type]
    assert sum(len(v) for v in fields.values()) >= MIN_PDP_CHARS
    assert validate_pdp_content(content) is True


def test_validate_ignores_whitespace_only_bodies() -> None:
    fields = {field: "   \n  " for field, _ in SECTION_HEADINGS}
    fields["current_skills_assessment"] = "a" * (MIN_PDP_CHARS + 10)
    content = PdpContent(**fields)  # type: ignore[arg-type]
    # 500-char bar cleared by one section, but whitespace-only bodies are not non-trivial.
    assert validate_pdp_content(content) is False


# --- render smoke tests -----------------------------------------------------------------


def test_build_pdf_returns_pdf_bytes() -> None:
    pdf = build_pdp_pdf(_full_content(), "Senior Data Engineer", "2027-01-01")
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_build_pdf_without_target_date() -> None:
    pdf = build_pdp_pdf(_full_content(), "Product Manager", None)
    assert pdf.startswith(b"%PDF")


def test_build_pdf_with_resources() -> None:
    resources = [
        LearningResourceRef(
            title="Advanced SQL",
            provider="Coursera",
            url="https://coursera.org/sql",
            skills=["sql"],
        ),
        LearningResourceRef(title="Kafka Basics"),
    ]
    pdf = build_pdp_pdf(_full_content(resources=resources), "Data Engineer", "2027-06")
    assert pdf.startswith(b"%PDF")


def test_build_pdf_survives_markup_special_chars() -> None:
    # Angle brackets, ampersands and bullets in the body must not break reportlab parsing.
    body = (
        "- First bullet with <angle> & ampersand\n"
        "* Second **bold** point\n"
        "### A subheading\n"
        "1. A numbered step with an unbalanced **marker"
    ) * 4
    content = _full_content(learning_objectives=body)
    pdf = build_pdp_pdf(content, "Role <x> & y", "2027")
    assert pdf.startswith(b"%PDF")


# --- inline markup helper ---------------------------------------------------------------


def test_inline_escapes_and_bolds() -> None:
    assert _inline("plain <b> & text") == "plain &lt;b&gt; &amp; text"
    assert _inline("a **bold** word") == "a <b>bold</b> word"


def test_inline_closes_unbalanced_bold() -> None:
    assert _inline("dangling **marker") == "dangling <b>marker</b>"
