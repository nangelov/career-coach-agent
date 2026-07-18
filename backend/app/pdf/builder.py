"""Styled PDP PDF builder + pre-render validation gate (design §5.2 / §5.7 / P7).

Ports the v1 reportlab builder (``legacy-code/helpers/helper.py``) onto the **structured**
:class:`~app.schemas.pdp.PdpContent` produced by P7-01, instead of re-parsing a raw LLM
markdown blob. Two exports:

* :func:`build_pdp_pdf` — renders the six typed sections (headings from
  :data:`~app.schemas.pdp.SECTION_HEADINGS`, the single source of truth) plus the cited
  learning resources into the same styled A4 PDF v1 produced, and returns the raw bytes.
* :func:`validate_pdp_content` — the pre-render gate P7-03's endpoint calls before returning
  a PDF. Keeps the v1 semantics (≥500 chars across sections, ≥4/6 sections with a non-trivial
  body) but reasons over the structured model rather than a string re-parse, so the endpoint
  gets a clear go/no-go signal instead of silently emitting a broken PDF.

Headings are never hardcoded here: both functions iterate ``SECTION_HEADINGS`` so the section
contract can only ever live in one place (:mod:`app.schemas.pdp`).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.schemas.pdp import SECTION_HEADINGS, LearningResourceRef, PdpContent

__all__ = [
    "MIN_PDP_CHARS",
    "MIN_REQUIRED_SECTIONS",
    "build_pdp_pdf",
    "validate_pdp_content",
]

#: v1 gate: the rendered plan must carry at least this many characters of section body across
#: all six sections (``validate_pdp_response`` rejected anything shorter as a broken/empty plan).
MIN_PDP_CHARS = 500

#: v1 gate: at least this many of the six sections must carry a non-trivial (non-empty) body —
#: the structured analogue of v1's "≥4 of 6 required section headings present" substring count
#: (headings are added deterministically now, so body substance is what actually varies).
MIN_REQUIRED_SECTIONS = 4

#: Fields mapping a resource to the *Recommended Training* section, so the citation list is
#: rendered right after that section body (§5.7 — grounded, not hallucinated, visible in output).
_RESOURCE_SECTION_FIELD = "recommended_training"


def validate_pdp_content(content: PdpContent) -> bool:
    """Pre-render gate: is this plan substantial enough to render (v1 ``validate_pdp_response``)?

    Reuses :data:`~app.schemas.pdp.SECTION_HEADINGS` (no second heading list) and keeps the v1
    thresholds: reject when the combined section bodies are shorter than :data:`MIN_PDP_CHARS`,
    or when fewer than :data:`MIN_REQUIRED_SECTIONS` of the six sections carry a non-trivial
    (non-empty after trim) body. P7-03 branches on this before returning a PDF.
    """
    bodies = [(getattr(content, field) or "").strip() for field, _ in SECTION_HEADINGS]
    if sum(len(body) for body in bodies) < MIN_PDP_CHARS:
        return False
    non_trivial = sum(1 for body in bodies if body)
    return non_trivial >= MIN_REQUIRED_SECTIONS


def build_pdp_pdf(content: PdpContent, career_goal: str, target_date: str | None) -> bytes:
    """Render ``content`` into a styled A4 PDF and return its raw bytes.

    Mirrors the v1 layout (``create_pdp_pdf``): a centred title, a career-goal / target-date /
    generated-on header, then each of the six :data:`~app.schemas.pdp.SECTION_HEADINGS`
    sections in v1's heading/body styles. The cited :attr:`PdpContent.resources` are rendered
    as a visible list under *Recommended Training and Development* (§5.7). Callers should run
    :func:`validate_pdp_content` first — this function renders whatever it is given.
    """
    styles = _build_styles()
    story: list[object] = [
        Paragraph("Personal Development Plan", styles["title"]),
        Spacer(1, 20),
        Paragraph(f"<b>Career Goal:</b> {escape(career_goal)}", styles["body"]),
        Paragraph(f"<b>Target Date:</b> {escape(target_date or 'Not specified')}", styles["body"]),
        Paragraph(
            f"<b>Generated on:</b> {datetime.now(UTC).strftime('%B %d, %Y')}",
            styles["body"],
        ),
        Spacer(1, 20),
    ]

    for field, heading in SECTION_HEADINGS:
        story.append(Paragraph(escape(heading), styles["heading"]))
        body = (getattr(content, field) or "").strip()
        for style_key, text in _body_lines(body):
            story.append(Paragraph(text, styles[style_key]))
        if field == _RESOURCE_SECTION_FIELD and content.resources:
            story.append(Paragraph("Cited Learning Resources", styles["subheading"]))
            for resource in content.resources:
                story.append(Paragraph(_resource_line(resource), styles["body"]))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=18,
    )
    doc.build(story)
    return buffer.getvalue()


def _build_styles() -> dict[str, ParagraphStyle]:
    """The four v1 paragraph styles (title / heading / subheading / body), keyed for lookup."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "CustomTitle",
            parent=base["Heading1"],
            fontSize=24,
            spaceAfter=30,
            textColor=HexColor("#2E86AB"),
            alignment=1,  # centre
        ),
        "heading": ParagraphStyle(
            "CustomHeading",
            parent=base["Heading2"],
            fontSize=16,
            spaceAfter=12,
            spaceBefore=20,
            textColor=HexColor("#A23B72"),
            leftIndent=0,
        ),
        "subheading": ParagraphStyle(
            "CustomSubHeading",
            parent=base["Heading3"],
            fontSize=14,
            spaceAfter=8,
            spaceBefore=12,
            textColor=HexColor("#F18F01"),
            leftIndent=20,
        ),
        "body": ParagraphStyle(
            "CustomBody",
            parent=base["Normal"],
            fontSize=11,
            spaceAfter=6,
            leftIndent=20,
            rightIndent=20,
        ),
    }


def _body_lines(body: str) -> list[tuple[str, str]]:
    """Convert a section *body* into ``(style_key, reportlab_markup)`` lines.

    Ports v1's ``prepare_pdf_content`` inline handling — ``###`` subheadings, ``**bold**``,
    ``-``/``*`` bullets, numbered lists — but only for the section *body* (the six ``##``
    headings are supplied by the caller from :data:`SECTION_HEADINGS`, never re-parsed here).
    Text is XML-escaped before markup is injected so ``<``/``&`` in the model output cannot
    break reportlab's paragraph parser.
    """
    lines: list[tuple[str, str]] = []
    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("###"):
            lines.append(("subheading", escape(line.lstrip("#").strip())))
        elif line.startswith(("- ", "* ")):
            lines.append(("body", f"• {_inline(line[2:])}"))
        elif re.match(r"^\d+\.", line):
            lines.append(("body", _inline(line)))
        else:
            lines.append(("body", _inline(line)))
    return lines


def _inline(text: str) -> str:
    """XML-escape ``text`` then convert paired ``**`` markers into reportlab ``<b>`` tags."""
    escaped = escape(text)
    while "**" in escaped:
        escaped = escaped.replace("**", "<b>", 1)
        if "**" in escaped:
            escaped = escaped.replace("**", "</b>", 1)
        else:
            # Unbalanced trailing ``**`` — close the tag so the markup stays valid.
            escaped += "</b>"
    return escaped


def _resource_line(resource: LearningResourceRef) -> str:
    """Render one cited resource as ``• <b>Title</b> — Provider (URL)`` (parts escaped)."""
    parts = [f"<b>{escape(resource.title)}</b>"]
    if resource.provider:
        parts.append(escape(resource.provider))
    if resource.url:
        parts.append(f"({escape(resource.url)})")
    return "• " + " — ".join(parts)
