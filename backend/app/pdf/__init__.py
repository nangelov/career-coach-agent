# pdf — reportlab PDF builders (ported from v1 helpers/helper.py in P7)
"""PDF generation package: the styled PDP builder + its pre-render validation gate."""

from app.pdf.builder import (
    MIN_PDP_CHARS,
    MIN_REQUIRED_SECTIONS,
    build_pdp_pdf,
    validate_pdp_content,
)

__all__ = [
    "MIN_PDP_CHARS",
    "MIN_REQUIRED_SECTIONS",
    "build_pdp_pdf",
    "validate_pdp_content",
]
