"""``DocumentParser`` — the engine-agnostic document-intelligence interface.

Design ref: app-design-and-features.md §5.1 — *"Wrap all of this behind a single
``DocumentParser`` interface in ``backend/app/ingestion/`` so engines can be swapped
without touching the agents."* This ABC is that seam: services and the later ingestion
task depend on :class:`DocumentParser`, never on a concrete engine. P5-01 ships the
``docling`` primary implementation (:mod:`app.ingestion.docling_parser`); P5-02's OCR
fallback and a future VLM path plug in behind the same contract.

Mirrors the ports-and-adapters shape the rest of the backend uses (``LLMClient`` in
``llm/client.py``, ``EmbeddingClient`` in ``llm/embeddings.py``): a narrow ABC here, the
SDK-bound adapter in a sibling module that imports its heavy dependency lazily so this
interface (and callers) import cleanly even where the engine is not installed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.ingestion.types import DocumentSource, ParsedDocument


class DocumentParseError(RuntimeError):
    """The engine could not parse the document (corrupt input, engine failure)."""


class UnsupportedDocumentError(DocumentParseError):
    """The source format could not be determined or is not supported by the engine.

    Raised, in particular, when a ``bytes`` source is passed with no ``filename`` or
    ``media_type`` hint, so the engine has no way to detect the format.
    """


class DocumentParser(ABC):
    """Interface every document-ingestion caller depends on — never a concrete engine.

    Implementations own the document-intelligence engine (layout analysis, OCR, table
    recovery) and translate its native result into a :class:`ParsedDocument`. Callers
    depend only on :meth:`parse`.
    """

    @abstractmethod
    async def parse(
        self,
        source: DocumentSource,
        *,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> ParsedDocument:
        """Parse one document into a structured :class:`ParsedDocument`.

        Args:
            source: A filesystem path (``str``) to an existing file, or the raw file
                ``bytes`` (e.g. an in-memory upload).
            filename: Original file name (e.g. ``"cv.pdf"``). Its extension is the
                primary format hint — **required** for ``bytes`` sources (a path carries
                its own name). Ignored formatting-wise for path sources but recorded in
                metadata when given.
            media_type: Optional MIME type (e.g. ``"application/pdf"``) used as a
                fallback format hint when ``filename`` has no usable extension.

        Returns:
            A :class:`ParsedDocument` with layout-aware Markdown, plain text, the
            engine's structured JSON, the detected format, and light metadata.

        Raises:
            UnsupportedDocumentError: The format could not be determined (e.g. ``bytes``
                with no ``filename``/``media_type``) or the engine does not support it.
            DocumentParseError: The engine failed to parse an otherwise-supported input.
        """
