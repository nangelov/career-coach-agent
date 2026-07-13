"""Extract inert plain text from an HTML page (stdlib parser, no new dependency).

Shared by every crawler that turns an untrusted fetched page into plain text for citation /
LLM grounding — the web searcher (§3) and the market-intel / learning-resource mining
crawlers (§5.6 / §5.7). Defined once here so the extraction (and its "drop script/style
bodies" rule) does not drift per-crawler (DRY).

A minimal :class:`~html.parser.HTMLParser` pass (no ``beautifulsoup4`` / ``selectolax``
dependency, per the OSS/budget posture §11): it drops the bodies of non-content tags
(``script`` / ``style`` / …) and collapses the remaining character data. Good enough to make
a real page into inert text — full readability heuristics are out of scope. The extracted
text is always **data, never instructions** (design §7.3); this module only produces the
text, the caller is responsible for fencing it before any LLM sees it.
"""

from __future__ import annotations

import logging
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

__all__ = ["html_to_text"]

#: Tags whose *content* is not human-visible text and must be dropped wholesale.
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "head"})


class _TextExtractor(HTMLParser):
    """Collect visible text from HTML, skipping ``<script>`` / ``<style>`` / etc. content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    @property
    def text(self) -> str:
        return " ".join(self._parts)


def html_to_text(html: str) -> str:
    """Extract collapsed plain text from an HTML string (fail-soft on malformed markup)."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception as exc:
        # Malformed markup: keep whatever text was gathered before the parser choked.
        logger.warning("HTML text extraction error: %s", exc)
    return parser.text
