"""Text-layer check — the "does this document have a usable text layer?" step.

Design ref: app-design-and-features.md §5.1 pipeline — *"has text layer? ── yes ──▶ direct
text extract  └─ no ──▶ rasterize → OCR"*. This module is that decision node, and it keys
off the **real** signal the primary engine already produced (:attr:`ParsedDocument.is_empty`
plus a low-text-density check) rather than re-probing the raw bytes — per the P5-01
architecture-review note (*"the OCR fallback must trigger off ``ParsedDocument.is_empty`` (or
a low-confidence signal), not re-invented"*).

Type detection itself is delegated to the engine: the format is already recorded in
:attr:`ParsedDocument.source_format`. What this step adds is the *text-layer* verdict —
whether the direct extract recovered enough usable text, or whether an OCR pass is warranted.

Kept engine-agnostic and side-effect-free (pure function over a :class:`ParsedDocument`) so
it is trivially testable in isolation and reusable by any tier of the ingestion chain.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ingestion.types import ParsedDocument


@dataclass(frozen=True)
class TextLayerAssessment:
    """The verdict of a text-layer check on one :class:`ParsedDocument`.

    Attributes:
        has_usable_text: ``True`` when the direct extract recovered enough text that an OCR
            fallback is not warranted.
        char_count: Non-whitespace-stripped character count of the recovered text.
        chars_per_page: ``char_count`` divided by ``page_count`` when the format has a page
            concept and a positive page count; ``None`` otherwise (page-less formats).
        reason: Short human-readable explanation of the verdict (for logs / metadata).
    """

    has_usable_text: bool
    char_count: int
    chars_per_page: float | None
    reason: str


class TextLayerCheck:
    """Decide whether a parsed document has a usable text layer or needs OCR.

    Two thresholds, both configurable:

    * ``min_chars`` — an absolute floor. Below it the extract is treated as effectively
      empty (a near-blank scan the engine could not read) → OCR.
    * ``min_chars_per_page`` — a density floor for paged formats (PDF). A multi-page PDF
      that yields only a handful of characters per page is almost certainly image-only
      (e.g. a scanned CV with a stray header) → OCR. Page-less formats (DOCX/Markdown) skip
      this check since they have no page concept.

    Defaults are deliberately conservative: a normal text CV clears them by a wide margin,
    so the fallback only fires on genuinely low/no-text documents (the acceptance-criteria
    "does NOT trigger on a normal text document" case).
    """

    DEFAULT_MIN_CHARS = 48
    DEFAULT_MIN_CHARS_PER_PAGE = 24.0

    def __init__(
        self,
        *,
        min_chars: int = DEFAULT_MIN_CHARS,
        min_chars_per_page: float = DEFAULT_MIN_CHARS_PER_PAGE,
    ) -> None:
        self._min_chars = min_chars
        self._min_chars_per_page = min_chars_per_page

    def assess(self, parsed: ParsedDocument) -> TextLayerAssessment:
        """Return the text-layer verdict for ``parsed`` (pure; no side effects)."""
        text = parsed.text.strip()
        char_count = len(text)

        if parsed.is_empty or char_count == 0:
            return TextLayerAssessment(
                has_usable_text=False,
                char_count=0,
                chars_per_page=None,
                reason="no text layer (empty extract)",
            )

        if char_count < self._min_chars:
            return TextLayerAssessment(
                has_usable_text=False,
                char_count=char_count,
                chars_per_page=None,
                reason=f"text below minimum ({char_count} < {self._min_chars} chars)",
            )

        pages = parsed.page_count
        if pages and pages > 0:
            density = char_count / pages
            if density < self._min_chars_per_page:
                return TextLayerAssessment(
                    has_usable_text=False,
                    char_count=char_count,
                    chars_per_page=density,
                    reason=(
                        f"low text density ({density:.1f} < "
                        f"{self._min_chars_per_page:.1f} chars/page)"
                    ),
                )
            return TextLayerAssessment(
                has_usable_text=True,
                char_count=char_count,
                chars_per_page=density,
                reason="usable text layer",
            )

        return TextLayerAssessment(
            has_usable_text=True,
            char_count=char_count,
            chars_per_page=None,
            reason="usable text layer",
        )
