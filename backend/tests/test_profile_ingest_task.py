"""Unit tests for the CV-ingestion Celery task core (P5-04, §5.1 / §5.3).

Exercise :func:`~app.tasks.profile_ingest.run_cv_ingestion` — the injectable, testable heart
of the task — with fakes for every collaborator (parser / structurer / embedder / DB), so no
real docling / HF / Postgres / Celery is involved. Covers the acceptance criteria:

* the full parse → structure → persist pipeline runs end-to-end and reports progress via the
  callback (the Celery ``update_state`` seam) in the right order,
* on success a :class:`Profile` is upserted and exactly one
  ``KbDocument(source_type="user_cv")`` + its embedded ``KbChunk`` rows are written,
* a guest (``user_id=None``) has the job run but nothing persisted,
* unrecoverable parse/structuring errors propagate (→ Celery ``FAILURE``, not swallowed), and
* the size-bounded chunker behaves.

The real-schema persistence proof (against docker-compose Postgres) lives in
``test_profile_ingest_persistence.py`` (skips when no DB), matching the P2 live-DB convention.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.ingestion.parser import DocumentParseError, DocumentParser
from app.ingestion.profile import ProfileSchema, ProfileStructuringError
from app.ingestion.types import DocumentSource, ParsedDocument
from app.repositories.models.identity import Profile
from app.repositories.models.knowledge import KbChunk, KbDocument
from app.tasks.profile_ingest import (
    STATE_PARSING,
    STATE_PERSISTING,
    STATE_STRUCTURING,
    chunk_text,
    run_cv_ingestion,
)
from tests.fakes import FakeEmbeddingClient


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeParser(DocumentParser):
    """A :class:`DocumentParser` that returns a canned document or raises."""

    def __init__(
        self, document: ParsedDocument | None = None, *, error: Exception | None = None
    ) -> None:
        self._document = document
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def parse(
        self,
        source: DocumentSource,
        *,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> ParsedDocument:
        self.calls.append({"source": source, "filename": filename, "media_type": media_type})
        if self._error is not None:
            raise self._error
        assert self._document is not None
        return self._document


class FakeStructurer:
    """A structurer returning a canned :class:`ProfileSchema` or raising."""

    def __init__(
        self, profile: ProfileSchema | None = None, *, error: Exception | None = None
    ) -> None:
        self._profile = profile if profile is not None else ProfileSchema()
        self._error = error
        self.documents: list[ParsedDocument] = []

    async def structure(self, document: ParsedDocument) -> ProfileSchema:
        self.documents.append(document)
        if self._error is not None:
            raise self._error
        return self._profile


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class CapturingSession:
    """An ``AsyncSession`` double that records ``add``ed rows and fakes id assignment.

    Serves the persist path's two ``execute`` calls in order: (1) the existing-profile lookup
    (returns ``existing_profile``), (2) the delete of prior CV docs (result ignored). ``flush``
    assigns a uuid to any id-less :class:`KbDocument` so the chunk FKs have a parent id.
    """

    def __init__(self, *, existing_profile: Profile | None = None) -> None:
        self.added: list[Any] = []
        self.committed = False
        self._existing_profile = existing_profile
        self._execute_calls = 0

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        self._execute_calls += 1
        if self._execute_calls == 1:
            return _ScalarResult(self._existing_profile)
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
    """A :class:`PostgresConnectionProvider` double whose ``session()`` yields one session."""

    def __init__(self, session: CapturingSession) -> None:
        self.session_obj = session
        self.opened = 0

    def session(self) -> Any:
        provider = self

        class _Ctx:
            async def __aenter__(self) -> CapturingSession:
                provider.opened += 1
                return provider.session_obj

            async def __aexit__(self, *exc: Any) -> bool:
                return False

        return _Ctx()


class ExplodingDBProvider:
    """A DB provider that fails if touched — proves the guest path never persists."""

    def session(self) -> Any:
        raise AssertionError("guest ingestion must not open a DB session")


def _doc(text: str = "Jane Doe\n\nExperience: Data Engineer at Acme.") -> ParsedDocument:
    return ParsedDocument(
        markdown=f"# CV\n\n{text}",
        text=text,
        source_format="pdf",
        page_count=1,
        metadata={"ocr_fallback_used": False},
    )


def _profile() -> ProfileSchema:
    return ProfileSchema(skills=["Python", "SQL"], goals=["Become a staff engineer"])


# --------------------------------------------------------------------------- #
# run_cv_ingestion — user (persisting) path
# --------------------------------------------------------------------------- #
async def test_run_ingestion_persists_profile_and_chunks_for_user() -> None:
    parser = FakeParser(_doc())
    structurer = FakeStructurer(_profile())
    embedder = FakeEmbeddingClient(vector=[0.5] * 4)
    session = CapturingSession()
    db = CapturingDBProvider(session)
    states: list[str] = []

    user_id = uuid.uuid4()
    result = await run_cv_ingestion(
        content=b"%PDF-1.4",
        filename="cv.pdf",
        media_type="application/pdf",
        user_id=str(user_id),
        parser=parser,
        structurer=structurer,
        embedder=embedder,
        db=db,
        progress=lambda state, _meta: states.append(state),
    )

    # Progress reported in order, through the persist stage.
    assert states == [STATE_PARSING, STATE_STRUCTURING, STATE_PERSISTING]

    # A profile row carrying the structured data was added (create branch: none existed).
    profiles = [row for row in session.added if isinstance(row, Profile)]
    assert len(profiles) == 1
    assert profiles[0].user_id == user_id
    assert profiles[0].data == _profile().model_dump()

    # Exactly one user_cv KbDocument, plus one embedded chunk per chunk.
    docs = [row for row in session.added if isinstance(row, KbDocument)]
    assert len(docs) == 1
    assert docs[0].source_type == "user_cv"
    assert docs[0].user_id == user_id
    assert docs[0].title == "cv.pdf"

    chunks = [row for row in session.added if isinstance(row, KbChunk)]
    assert len(chunks) == result["chunk_count"] >= 1
    assert all(c.kb_document_id == docs[0].id for c in chunks)
    assert all(c.embedding == [0.5] * 4 for c in chunks)
    # Chunk indices are 0-based and contiguous.
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))

    assert session.committed is True
    assert result["persisted"] is True
    assert result["kb_document_id"] == str(docs[0].id)
    assert result["profile"] == _profile().model_dump()


async def test_run_ingestion_updates_existing_profile_in_place() -> None:
    existing = Profile(user_id=uuid.uuid4(), data={"skills": ["old"]})
    parser = FakeParser(_doc())
    structurer = FakeStructurer(_profile())
    session = CapturingSession(existing_profile=existing)
    db = CapturingDBProvider(session)

    await run_cv_ingestion(
        content=b"%PDF",
        filename="cv.pdf",
        media_type="application/pdf",
        user_id=str(existing.user_id),
        parser=parser,
        structurer=structurer,
        embedder=FakeEmbeddingClient(vector=[0.1] * 4),
        db=db,
    )

    # Upsert = update in place: the existing row's data was overwritten, no new Profile added.
    assert existing.data == _profile().model_dump()
    assert [row for row in session.added if isinstance(row, Profile)] == []


# --------------------------------------------------------------------------- #
# run_cv_ingestion — guest path (no persistence)
# --------------------------------------------------------------------------- #
async def test_run_ingestion_guest_does_not_persist() -> None:
    parser = FakeParser(_doc())
    structurer = FakeStructurer(_profile())
    states: list[str] = []

    result = await run_cv_ingestion(
        content=b"%PDF",
        filename="cv.pdf",
        media_type="application/pdf",
        user_id=None,
        parser=parser,
        structurer=structurer,
        embedder=FakeEmbeddingClient(),
        db=ExplodingDBProvider(),
        progress=lambda state, _meta: states.append(state),
    )

    assert states == [STATE_PARSING, STATE_STRUCTURING]  # no persist stage
    assert result["persisted"] is False
    assert result["kb_document_id"] is None
    assert result["profile"] == _profile().model_dump()


# --------------------------------------------------------------------------- #
# run_cv_ingestion — error propagation (not swallowed → Celery FAILURE)
# --------------------------------------------------------------------------- #
async def test_run_ingestion_propagates_parse_error() -> None:
    parser = FakeParser(error=DocumentParseError("corrupt"))
    with pytest.raises(DocumentParseError):
        await run_cv_ingestion(
            content=b"bad",
            filename="cv.pdf",
            media_type="application/pdf",
            user_id="u1",
            parser=parser,
            structurer=FakeStructurer(),
            embedder=FakeEmbeddingClient(),
            db=ExplodingDBProvider(),
        )


async def test_run_ingestion_propagates_structuring_error() -> None:
    parser = FakeParser(_doc())
    structurer = FakeStructurer(error=ProfileStructuringError("bad output"))
    with pytest.raises(ProfileStructuringError):
        await run_cv_ingestion(
            content=b"%PDF",
            filename="cv.pdf",
            media_type="application/pdf",
            user_id="u1",
            parser=parser,
            structurer=structurer,
            embedder=FakeEmbeddingClient(),
            db=ExplodingDBProvider(),
        )


# --------------------------------------------------------------------------- #
# chunk_text
# --------------------------------------------------------------------------- #
def test_chunk_text_empty_returns_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_chunk_text_short_returns_single_chunk() -> None:
    assert chunk_text("A short CV.") == ["A short CV."]


def test_chunk_text_long_splits_and_bounds_each_chunk() -> None:
    text = "\n\n".join(f"Paragraph {i} " + ("x" * 300) for i in range(10))
    chunks = chunk_text(text, max_chars=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)
    # No content is dropped: every paragraph marker survives somewhere.
    joined = "\n".join(chunks)
    assert all(f"Paragraph {i}" in joined for i in range(10))


def test_chunk_text_hard_wraps_oversized_paragraph() -> None:
    text = "y" * 2500
    chunks = chunk_text(text, max_chars=1000, overlap=100)
    assert len(chunks) >= 3
    assert all(len(c) <= 1000 for c in chunks)
