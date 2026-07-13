"""Unit tests for the taxonomy seed core (P6-01, §5.6 / §6 decision 15).

Exercise :mod:`app.ingestion.taxonomy_seed` — the injectable, testable heart of the seed — with
fakes for every collaborator (embedder / DB), so no real ``sentence-transformers`` / Postgres /
Celery / network is involved. Covers the acceptance criteria:

* the parse/normalize step validates + normalizes the fixture (and rejects malformed entries),
* the bundled fixture is present, valid, and read from disk (no scraping/network),
* the seed writes shared curated ``kb_documents`` (``user_id IS NULL``) + embedded ``kb_chunks``
  via the existing P2 embedding/write helpers, and
* re-running is idempotent — it deletes the prior curated docs for each source before inserting,
  so no duplicate rows accumulate.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.ingestion.taxonomy_seed import (
    _ALLOWED_TAXONOMIES,
    CURATED_SOURCE_TYPE,
    STATE_EMBEDDING,
    STATE_PERSISTING,
    TaxonomyOccupation,
    TaxonomySeedError,
    load_seed_occupations,
    parse_occupations,
    run_taxonomy_seed,
)
from app.repositories.kb_kinds import TAXONOMY_KIND
from app.repositories.models.knowledge import KbChunk, KbDocument
from tests.fakes import FakeEmbeddingClient


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class CapturingSession:
    """An ``AsyncSession`` double that records executed statements + added rows.

    Serves the upsert path: the first (and only) ``execute`` is the idempotency delete (its
    result is ignored). ``flush`` assigns a uuid to any id-less :class:`KbDocument` so the chunk
    FKs have a parent id.
    """

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.executed: list[Any] = []
        self.committed = False

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        self.executed.append(statement)
        return object()  # delete() result — not inspected

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if isinstance(obj, KbDocument) and obj.id is None:
                obj.id = uuid.uuid4()

    async def commit(self) -> None:
        self.committed = True


class CapturingDBProvider:
    """A ``PostgresConnectionProvider`` double whose ``session()`` yields the given session(s)."""

    def __init__(self, *sessions: CapturingSession) -> None:
        self._sessions = list(sessions)
        self.opened = 0

    def session(self) -> Any:
        provider = self

        class _Ctx:
            async def __aenter__(self) -> CapturingSession:
                index = provider.opened
                provider.opened += 1
                return provider._sessions[index]

            async def __aexit__(self, *exc: Any) -> bool:
                return False

        return _Ctx()


class ExplodingDBProvider:
    """A DB provider that fails if touched — proves the empty-input path never opens a session."""

    def session(self) -> Any:
        raise AssertionError("empty seed must not open a DB session")


def _raw_entry(**overrides: Any) -> dict[str, Any]:
    entry = {
        "taxonomy": "onet",
        "id": "15-1252.00",
        "title": "Software Developers",
        "description": "Design and develop software.",
        "skills": ["Python", "debugging"],
    }
    entry.update(overrides)
    return entry


# --------------------------------------------------------------------------- #
# parse / normalize
# --------------------------------------------------------------------------- #
def test_parse_normalizes_entry() -> None:
    [occ] = parse_occupations([_raw_entry(taxonomy="ONET", skills=[" Python ", "Python", ""])])

    assert occ.taxonomy == "onet"  # lowercased
    assert occ.taxonomy_id == "15-1252.00"
    assert occ.source == "onet:15-1252.00"
    assert occ.skills == ("Python",)  # stripped + de-duped, blank dropped
    # to_document_text folds title, description, and skills into the embeddable text.
    text = occ.to_document_text()
    assert "Software Developers" in text
    assert "Design and develop software." in text
    assert "Related skills: Python" in text


def test_parse_accepts_esco_and_onet() -> None:
    occs = parse_occupations(
        [_raw_entry(taxonomy="esco", id="2512"), _raw_entry(taxonomy="onet", id="15-1252.00")]
    )
    assert {o.taxonomy for o in occs} == {"esco", "onet"}


def test_parse_rejects_unknown_taxonomy() -> None:
    with pytest.raises(TaxonomySeedError, match="taxonomy must be"):
        parse_occupations([_raw_entry(taxonomy="linkedin")])


@pytest.mark.parametrize("field", ["taxonomy", "id", "title", "description"])
def test_parse_rejects_missing_required_field(field: str) -> None:
    with pytest.raises(TaxonomySeedError, match="missing or empty|taxonomy must be"):
        parse_occupations([_raw_entry(**{field: ""})])


def test_parse_rejects_non_list_fixture() -> None:
    with pytest.raises(TaxonomySeedError, match="must be a JSON array"):
        parse_occupations({"taxonomy": "onet"})


def test_parse_rejects_bad_skills_type() -> None:
    with pytest.raises(TaxonomySeedError, match="'skills' must be a list of strings"):
        parse_occupations([_raw_entry(skills="Python")])


def test_parse_rejects_duplicate_source() -> None:
    with pytest.raises(TaxonomySeedError, match="duplicate source"):
        parse_occupations([_raw_entry(), _raw_entry()])


# --------------------------------------------------------------------------- #
# bundled fixture (read from disk — no network)
# --------------------------------------------------------------------------- #
def test_bundled_fixture_loads_and_is_valid() -> None:
    occupations = load_seed_occupations()

    assert len(occupations) >= 20  # representative subset
    # Every entry is a valid, uniquely-sourced ESCO/O*NET occupation with skills.
    assert all(o.taxonomy in _ALLOWED_TAXONOMIES for o in occupations)
    assert len({o.source for o in occupations}) == len(occupations)
    assert all(o.skills for o in occupations)
    # Both taxonomies are represented (the task asks for ESCO and/or O*NET; we include both).
    assert {o.taxonomy for o in occupations} == set(_ALLOWED_TAXONOMIES)


# --------------------------------------------------------------------------- #
# run_taxonomy_seed — write path
# --------------------------------------------------------------------------- #
async def test_run_seed_writes_shared_curated_documents_and_chunks() -> None:
    occupations = parse_occupations(
        [_raw_entry(taxonomy="esco", id="2512"), _raw_entry(taxonomy="onet", id="15-1252.00")]
    )
    embedder = FakeEmbeddingClient(vector=[0.5] * 4)
    session = CapturingSession()
    db = CapturingDBProvider(session)
    states: list[str] = []

    result = await run_taxonomy_seed(
        occupations=occupations,
        embedder=embedder,
        db=db,
        progress=lambda state, _meta: states.append(state),
    )

    assert states == [STATE_EMBEDDING, STATE_PERSISTING]

    docs = [row for row in session.added if isinstance(row, KbDocument)]
    assert len(docs) == 2
    for doc in docs:
        assert doc.user_id is None  # shared KB
        assert doc.source_type == CURATED_SOURCE_TYPE
        assert doc.source in {"esco:2512", "onet:15-1252.00"}
        assert doc.meta["taxonomy"] in _ALLOWED_TAXONOMIES
        assert doc.meta["skills"] == ["Python", "debugging"]
        # Stamped with the taxonomy kind so _resolve_baseline can filter it out of the shared
        # curated corpus (role-profile summaries / learning resources share source_type).
        assert doc.meta["kind"] == TAXONOMY_KIND

    chunks = [row for row in session.added if isinstance(row, KbChunk)]
    assert len(chunks) == result["chunks_written"] >= 2
    assert all(c.embedding == [0.5] * 4 for c in chunks)
    # Each occupation's chunk indices are 0-based per document.
    for doc in docs:
        doc_chunks = [c for c in chunks if c.kb_document_id == doc.id]
        assert [c.chunk_index for c in doc_chunks] == list(range(len(doc_chunks)))

    assert session.committed is True
    assert result["occupations"] == 2
    assert result["documents_written"] == 2


async def test_run_seed_deletes_prior_docs_for_sources_before_insert() -> None:
    """Idempotency: the upsert issues a source-scoped delete before inserting the fresh docs."""
    occupations = parse_occupations(
        [_raw_entry(taxonomy="esco", id="2512"), _raw_entry(taxonomy="onet", id="15-1252.00")]
    )
    session = CapturingSession()
    db = CapturingDBProvider(session)

    await run_taxonomy_seed(
        occupations=occupations, embedder=FakeEmbeddingClient(vector=[0.1] * 4), db=db
    )

    # Exactly one statement executed (the delete), and it ran before any row was flushed with id.
    assert len(session.executed) == 1
    delete_stmt = session.executed[0]
    # The delete is scoped to this batch's sources (compiled bind params carry them).
    param_values: set[Any] = set()
    for value in delete_stmt.compile().params.values():
        if isinstance(value, (list, tuple)):
            param_values.update(value)
        else:
            param_values.add(value)
    assert {"esco:2512", "onet:15-1252.00"} <= param_values
    # ...and scoped to the shared curated vocabulary (not a user's private docs).
    assert CURATED_SOURCE_TYPE in param_values


async def test_run_seed_repeat_run_writes_same_counts() -> None:
    """Re-running yields the same document/chunk counts — delete-then-insert, no accumulation."""
    occupations = parse_occupations([_raw_entry(taxonomy="esco", id="2512")])
    session_a = CapturingSession()
    session_b = CapturingSession()
    db = CapturingDBProvider(session_a, session_b)
    embedder = FakeEmbeddingClient(vector=[0.2] * 4)

    first = await run_taxonomy_seed(occupations=occupations, embedder=embedder, db=db)
    second = await run_taxonomy_seed(occupations=occupations, embedder=embedder, db=db)

    assert first == second
    assert first["documents_written"] == 1
    # Each run adds exactly one document (the delete clears the prior one on a real DB).
    assert len([r for r in session_a.added if isinstance(r, KbDocument)]) == 1
    assert len([r for r in session_b.added if isinstance(r, KbDocument)]) == 1


async def test_run_seed_empty_occupations_does_not_touch_db() -> None:
    result = await run_taxonomy_seed(
        occupations=[], embedder=FakeEmbeddingClient(), db=ExplodingDBProvider()
    )
    assert result == {"occupations": 0, "documents_written": 0, "chunks_written": 0}


def test_occupation_source_and_text() -> None:
    occ = TaxonomyOccupation(
        taxonomy="onet",
        taxonomy_id="15-2051.00",
        title="Data Scientists",
        description="Analyze data.",
        skills=("Python", "ML"),
    )
    assert occ.source == "onet:15-2051.00"
    expected = "Data Scientists\n\nAnalyze data.\n\nRelated skills: Python, ML"
    assert occ.to_document_text() == expected
