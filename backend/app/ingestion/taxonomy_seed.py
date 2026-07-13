"""Taxonomy seed — ingest a bundled ESCO/O*NET occupation+skill subset into the shared KB (P6-01).

This finally populates the RAG corpus no earlier phase owned (§5.6 *"why taxonomy-first"*,
§6 decision 15): a curated, **static** subset of ESCO / O*NET occupations and their associated
skills, written as **shared** ``kb_documents`` (``user_id IS NULL``, ``source_type='curated'``)
with embedded ``kb_chunks``. There is **no scraping and no live external HTTP call** anywhere in
this path — the data is a checked-in fixture read from disk (see ``data/README.md`` for
provenance/licensing: ESCO is CC BY 4.0, O*NET is US public domain, both free to redistribute).

This module is the **injectable, testable core** (no Celery/broker/DB driver required):

* :func:`load_seed_occupations` / :func:`parse_occupations` — read + normalize the fixture into
  validated :class:`TaxonomyOccupation` records (the parse/normalize step unit tests cover).
* :func:`run_taxonomy_seed` — embed each occupation (reusing the P2 ``EmbeddingClient``) and
  **idempotently upsert** it into the KB (reusing
  :func:`app.repositories.vector_search.add_kb_chunk` — no second embedding/write path). Keyed
  on ``source = "<taxonomy>:<id>"``: re-running replaces
  the document for each source (chunks cascade) rather than duplicating rows.

The Celery wrapper + CLI live in :mod:`app.tasks.taxonomy`; this module owns the logic so a unit
test can drive it with fakes.

**Upgrade path (documented, not built here).** To swap the curated sample for the full ESCO/O*NET
bulk download, replace ``data/taxonomy_seed.json`` (or pass a new path) with a normalized export of
the offline bulk distributions — no code change to this pipeline is required. See
``app/ingestion/data/README.md`` for the mapping steps. This task ships the *ingestion pipeline*,
not the full live dataset.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import delete

from app.ingestion.chunking import chunk_text
from app.repositories.kb_kinds import TAXONOMY_KIND
from app.repositories.models.knowledge import KbDocument
from app.repositories.vector_search import add_kb_chunk

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.llm.embeddings import EmbeddingClient

#: The ``KbDocument.source_type`` for shared curated taxonomy content — the existing
#: ``ck_kb_documents_source_type`` check-constraint value (do NOT add a new one, per the task).
CURATED_SOURCE_TYPE = "curated"

#: Accepted taxonomy vocabularies. ``source`` becomes ``"<taxonomy>:<id>"`` (e.g.
#: ``"onet:15-1252.00"``, ``"esco:2512"``) — the idempotency key.
_ALLOWED_TAXONOMIES = ("esco", "onet")

#: Default bundled fixture (checked in; read from disk — no network). See ``data/README.md``.
DEFAULT_SEED_PATH = Path(__file__).resolve().parent / "data" / "taxonomy_seed.json"

#: Progress stages surfaced to the Celery ``update_state`` seam (kept distinct from Celery's
#: built-in PENDING/SUCCESS/FAILURE so a poller can show a meaningful stage).
STATE_EMBEDDING = "EMBEDDING"
STATE_PERSISTING = "PERSISTING"


class TaxonomySeedError(ValueError):
    """A seed fixture entry is malformed (missing/invalid field). Fail loud, not silent."""


@dataclass(frozen=True)
class TaxonomyOccupation:
    """One normalized occupation record from the taxonomy seed fixture.

    ``taxonomy`` + ``taxonomy_id`` form the stable identity; :attr:`source` is the
    ``kb_documents.source`` value and the idempotency key.
    """

    taxonomy: str
    taxonomy_id: str
    title: str
    description: str
    skills: tuple[str, ...]

    @property
    def source(self) -> str:
        """The ``kb_documents.source`` value / idempotency key, e.g. ``"onet:15-1252.00"``."""
        return f"{self.taxonomy}:{self.taxonomy_id}"

    def to_document_text(self) -> str:
        """The embeddable document text: title, description, and the associated skills.

        Skills are folded into the text (not just metadata) so lexical + vector retrieval can
        match a query on a skill name to the occupation that requires it (§5.6 taxonomy-first).
        """
        parts = [self.title, self.description]
        if self.skills:
            parts.append("Related skills: " + ", ".join(self.skills))
        return "\n\n".join(part for part in parts if part)


class SessionProvider(Protocol):
    """The DB-session capability :func:`run_taxonomy_seed` needs (the real Postgres provider).

    Structural (not the concrete ``PostgresConnectionProvider``) so a unit test injects a fake
    session with no real driver — the repository layer still owns all datastore access (§8).
    """

    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


def _require_str(entry: dict[str, Any], key: str, *, where: str) -> str:
    """Return a non-empty stripped string field or raise :class:`TaxonomySeedError`."""
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TaxonomySeedError(f"{where}: missing or empty required field {key!r}")
    return value.strip()


def parse_occupations(raw: Any) -> list[TaxonomyOccupation]:
    """Normalize the raw fixture (a list of dicts) into validated :class:`TaxonomyOccupation`.

    Validates every entry: ``taxonomy`` (one of :data:`_ALLOWED_TAXONOMIES`), ``id``, ``title``,
    ``description`` are required non-empty strings; ``skills`` (optional) must be a list of
    strings (blank entries dropped, order + duplicates-removed preserved). Raises
    :class:`TaxonomySeedError` on any malformed entry (fail loud) and on a duplicate ``source``
    within the fixture (an ambiguous idempotency key).
    """
    if not isinstance(raw, list):
        raise TaxonomySeedError("seed fixture must be a JSON array of occupation objects")

    occupations: list[TaxonomyOccupation] = []
    seen_sources: set[str] = set()
    for index, entry in enumerate(raw):
        where = f"entry[{index}]"
        if not isinstance(entry, dict):
            raise TaxonomySeedError(f"{where}: expected an object, got {type(entry).__name__}")

        taxonomy = _require_str(entry, "taxonomy", where=where).lower()
        if taxonomy not in _ALLOWED_TAXONOMIES:
            raise TaxonomySeedError(
                f"{where}: taxonomy must be one of {_ALLOWED_TAXONOMIES}, got {taxonomy!r}"
            )
        taxonomy_id = _require_str(entry, "id", where=where)
        title = _require_str(entry, "title", where=where)
        description = _require_str(entry, "description", where=where)

        raw_skills = entry.get("skills", [])
        if not isinstance(raw_skills, list) or not all(isinstance(s, str) for s in raw_skills):
            raise TaxonomySeedError(f"{where}: 'skills' must be a list of strings")
        # Drop blanks, dedupe preserving first-seen order.
        skills = tuple(dict.fromkeys(s.strip() for s in raw_skills if s.strip()))

        occupation = TaxonomyOccupation(
            taxonomy=taxonomy,
            taxonomy_id=taxonomy_id,
            title=title,
            description=description,
            skills=skills,
        )
        if occupation.source in seen_sources:
            raise TaxonomySeedError(f"{where}: duplicate source {occupation.source!r} in fixture")
        seen_sources.add(occupation.source)
        occupations.append(occupation)

    return occupations


def load_seed_occupations(path: Path | str = DEFAULT_SEED_PATH) -> list[TaxonomyOccupation]:
    """Read + normalize the bundled seed fixture from disk (no network).

    See :func:`parse_occupations` for the validation applied.
    """
    text = Path(path).read_text(encoding="utf-8")
    return parse_occupations(json.loads(text))


@dataclass(frozen=True)
class _PreparedOccupation:
    """An occupation with its computed chunks + embeddings, ready to persist."""

    occupation: TaxonomyOccupation
    content: str
    chunks: list[str]
    embeddings: list[list[float]]


async def run_taxonomy_seed(
    *,
    occupations: Sequence[TaxonomyOccupation],
    embedder: EmbeddingClient,
    db: SessionProvider,
    progress: Callable[[str, dict[str, Any]], None] = lambda _state, _meta: None,
) -> dict[str, Any]:
    """Embed + idempotently upsert ``occupations`` into the shared KB; return a result summary.

    The injectable core of the seed (no Celery/broker): all collaborators are passed in so a
    unit test drives it with fakes. Embedding runs first (outside the DB transaction, to keep it
    short); persistence is one transaction that **replaces** any existing curated document per
    ``source`` before inserting the fresh one — so re-running produces no duplicate rows.

    Returns a JSON-serializable dict (the Celery task result):
    ``{"occupations", "documents_written", "chunks_written"}``.
    """
    progress(STATE_EMBEDDING, {"stage": "embedding", "message": "Embedding taxonomy occupations."})
    prepared: list[_PreparedOccupation] = []
    for occupation in occupations:
        content = occupation.to_document_text()
        chunks = chunk_text(content)
        embeddings = await embedder.embed_documents(chunks) if chunks else []
        prepared.append(
            _PreparedOccupation(
                occupation=occupation, content=content, chunks=chunks, embeddings=embeddings
            )
        )

    progress(
        STATE_PERSISTING,
        {"stage": "persisting", "message": "Writing occupations to the shared knowledge base."},
    )
    chunks_written = await _upsert_occupations(db, prepared)
    return {
        "occupations": len(prepared),
        "documents_written": len(prepared),
        "chunks_written": chunks_written,
    }


async def _upsert_occupations(db: SessionProvider, prepared: Sequence[_PreparedOccupation]) -> int:
    """Idempotently replace the curated KB documents for these sources; return chunks written.

    One transaction (the caller owns the boundary — §8 layering): bulk-delete any existing
    shared curated documents whose ``source`` is in this batch (their chunks removed by the
    ``kb_chunks`` ON DELETE CASCADE FK), then insert the fresh documents + embedded chunks via
    the existing :func:`~app.repositories.vector_search.add_kb_chunk` helper. Re-running with the
    same fixture therefore leaves **exactly one** document per source.
    """
    if not prepared:
        return 0

    sources = [item.occupation.source for item in prepared]
    total_chunks = 0
    async with db.session() as session:
        # Remove any prior curated doc for these sources (shared rows: user_id IS NULL). Child
        # kb_chunks are removed by the ON DELETE CASCADE FK. This is what makes the seed idempotent.
        await session.execute(
            delete(KbDocument).where(
                KbDocument.user_id.is_(None),
                KbDocument.source_type == CURATED_SOURCE_TYPE,
                KbDocument.source.in_(sources),
            )
        )

        for item in prepared:
            occupation = item.occupation
            document = KbDocument(
                title=occupation.title,
                source=occupation.source,
                source_type=CURATED_SOURCE_TYPE,
                user_id=None,
                content=item.content,
                meta={
                    "kind": TAXONOMY_KIND,
                    "taxonomy": occupation.taxonomy,
                    "taxonomy_id": occupation.taxonomy_id,
                    "skills": list(occupation.skills),
                },
            )
            session.add(document)
            await session.flush()  # populate document.id for the chunk FKs

            for index, (chunk, embedding) in enumerate(
                zip(item.chunks, item.embeddings, strict=True)
            ):
                await add_kb_chunk(
                    session,
                    kb_document_id=document.id,
                    chunk_index=index,
                    content=chunk,
                    embedding=embedding,
                    meta={
                        "kind": TAXONOMY_KIND,
                        "taxonomy": occupation.taxonomy,
                        "taxonomy_id": occupation.taxonomy_id,
                        "source": occupation.source,
                    },
                )
                total_chunks += 1

        await session.commit()
    return total_chunks
