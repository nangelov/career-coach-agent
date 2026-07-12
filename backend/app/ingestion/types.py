"""Provider-agnostic document-ingestion vocabulary.

These types are what the rest of the app (services, later the structured-profile
parser in P5-03, the Celery ingestion task in P5-04) speaks — deliberately decoupled
from any concrete document-intelligence engine (``docling``, a future OCR/VLM path).
Nothing outside ``app/ingestion/`` imports the engine SDK; the concrete parser
(:mod:`app.ingestion.docling_parser`) translates the engine's native result into a
:class:`ParsedDocument`.

Design ref: app-design-and-features.md §5.1 (*"structured Markdown/JSON (layout, tables,
reading order)"* behind a single ``DocumentParser`` interface).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

#: What :meth:`app.ingestion.parser.DocumentParser.parse` accepts as the document
#: source: a filesystem path (``str`` / ``pathlib.Path``, passed to callers as ``str``)
#: **or** the raw file ``bytes`` (e.g. an in-memory upload). ``bytes`` sources need a
#: ``filename``/``media_type`` hint so the engine can detect the format — see the
#: interface docstring.
DocumentSource = str | bytes


class ParsedDocument(BaseModel):
    """The engine-agnostic result of parsing one document.

    This is the single representation later ingestion steps depend on:

    * :attr:`markdown` — layout-aware Markdown (sections, tables, reading order) — the
      primary form the LLM-assisted structured-profile parser (P5-03) will consume.
    * :attr:`text` — plain text with no Markdown scaffolding, for cheap chunking/embedding.
    * :attr:`structured` — the engine's structured JSON export (element tree with layout,
      tables, provenance) for callers that need richer structure than Markdown.
    * :attr:`source_format` — the detected input format (e.g. ``"docx"``, ``"pdf"``),
      lower-cased.
    * :attr:`page_count` — number of pages when the format has a page concept
      (``None`` for page-less formats like DOCX/Markdown).
    * :attr:`metadata` — free-form engine metadata (kept small and JSON-serializable).
    """

    markdown: str
    text: str
    structured: dict[str, Any] = Field(default_factory=dict)
    source_format: str
    page_count: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """True when the parser recovered no usable text (whitespace-only).

        A downstream step (P5-02 OCR fallback) keys on this to decide whether the
        direct text extract failed and a rasterize→OCR pass is needed.
        """
        return not self.text.strip()
