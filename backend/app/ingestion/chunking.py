"""Dependency-free, size-bounded text chunker shared across ingestion paths (§5.1).

Chunking is an **ingestion** concern (turning a source document's text into the
retrieval-unit windows that get embedded into ``kb_chunks``), not a Celery-task concern —
so it lives here and is reused by every ingestion producer rather than duplicated. Both the
CV-ingestion task (:mod:`app.tasks.profile_ingest`) and the taxonomy seed
(:mod:`app.ingestion.taxonomy_seed`) call :func:`chunk_text`; keeping one implementation
keeps the embedded-chunk shape identical regardless of the source (DRY).

Deliberately simple and dependency-free (KISS — no external text splitter): paragraph-aware
greedy packing with a small carry-over on hard-wrapped oversized paragraphs. Deterministic,
so unit tests can assert exact output.
"""

from __future__ import annotations

#: Default chunking bounds. A ~1k-char window with a small overlap keeps each chunk
#: semantically coherent while preserving context across boundaries — suited to the short
#: documents these ingestion paths produce (CVs, taxonomy occupations).
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 150


def chunk_text(
    text: str,
    *,
    max_chars: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split ``text`` into size-bounded, slightly-overlapping chunks for embedding.

    Paragraph-aware greedy packing: paragraphs (blank-line separated) are packed into windows
    up to ``max_chars``; a single paragraph longer than ``max_chars`` is hard-wrapped with an
    ``overlap``-char carry so context is not lost at the split. Whitespace-only input yields no
    chunks. Deterministic and dependency-free (KISS — no external text splitter).
    """
    normalized = (text or "").strip()
    if not normalized:
        return []
    if overlap >= max_chars:  # defensive: overlap must be strictly smaller than the window
        overlap = max_chars // 4

    # Split into paragraphs, then hard-wrap any oversized paragraph into <= max_chars pieces.
    pieces: list[str] = []
    for para in (p.strip() for p in normalized.split("\n\n")):
        if not para:
            continue
        if len(para) <= max_chars:
            pieces.append(para)
            continue
        start = 0
        step = max_chars - overlap
        while start < len(para):
            pieces.append(para[start : start + max_chars].strip())
            start += step

    # Greedily pack consecutive pieces into windows up to max_chars.
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + 2 + len(piece) <= max_chars:
            current = f"{current}\n\n{piece}"
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks
