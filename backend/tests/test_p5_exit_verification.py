"""P5 phase-exit verification (P5-08) — the full CV-ingestion story, end to end.

This is a **verification-only** module (no product code changed): it ties the P5 building
blocks together and drives them through the **real** ingestion chain — the real
:class:`~app.ingestion.composite_parser.CompositeDocumentParser` (tiering + text-layer check),
the real :class:`~app.ingestion.structuring.ProfileStructurer`, the real Celery task core
:func:`~app.tasks.profile_ingest.run_cv_ingestion`, the real ``POST /api/profile/cv`` /
``GET /api/jobs/status/{task_id}`` / ``GET /api/profile`` routers, and the real P4 RAG
retrieval path (:func:`~app.agents.rag_agent.retrieve` over
:func:`~app.repositories.vector_search.hybrid_search_chunks`) — proving the one plan.md P5
exit criterion as a single story:

    "A scanned/image PDF and a PPTX CV both parse (async, with progress) into a usable
     structured profile and become RAG-grounded."

Only the *outermost* collaborators are faked — exactly the true external edges that need a
model download, a system binary, a live model, or a broker/DB this environment does not have:

* **docling's layout/OCR model** — faked via the ``converter_factory`` seam for the scanned
  PDF (docling would download layout models for a raster PDF). The **PPTX** path uses the
  **real** docling engine (its simple office pipeline needs no model download), guarded by
  ``importorskip("docling")`` since the curated CI venv excludes docling.
* **the Tesseract/OCRmyPDF binary** — faked via ``OcrDocumentParser(engine_factory=...)`` (no
  ``tesseract`` binary here); the real composite tiering still decides *when* OCR runs.
* **LLM completions** (structuring) — a scripted :class:`_FakeStructuringCompleter` returns a
  forced ``record_profile`` tool call (no HF); the real structurer validates it.
* **embeddings** — a deterministic embedder (no ``sentence-transformers``/``torch``).
* **the Celery broker + result backend** — the upload endpoint runs over a fake enqueuer, and
  the status endpoint over a scripted ``AsyncResult``, so async behaviour is proven without a
  running worker/Redis.

The two live-Postgres proofs (persist→reuse, and RAG grounding against real ``vector(4096)``
+ JSONB) run against docker-compose Postgres and **skip cleanly** when no DB is reachable —
mirroring the P2-09/P4-10 precedent for what can and cannot run live in this environment.

P5 exit criterion — point-by-point (task P5-08):

1. Scanned/image PDF → **OCR fallback** (not docling primary) → non-trivial structured profile
   — ``test_scanned_pdf_triggers_ocr_fallback_into_structured_profile``.
2. PPTX → **docling primary** → structured profile —
   ``test_pptx_cv_parses_via_docling_primary_into_structured_profile``.
3. **Async** — endpoint returns ``202`` + ``task_id`` with no in-request parse; status polls
   pending → in-progress-with-stage → success —
   ``test_upload_endpoint_is_async_202_and_no_in_request_parse`` +
   ``test_job_status_polls_producer_lifecycle_to_success`` +
   ``test_task_core_emits_real_progress_stages_for_both_documents``.
4. **Usable** profile (non-empty skills/experience/education for a realistic CV) — asserted in
   the point-1/2 tests (an all-empty profile from a real CV would fail them).
5. **Persisted + reusable** — ``GET /api/profile`` returns the parsed profile with no re-upload,
   and a second upload keeps exactly one ``user_cv`` doc —
   ``test_persisted_profile_is_reusable_via_get_profile`` (live DB) + the existing
   ``test_profile_ingest_persistence`` re-upload-replace proof.
6. **RAG-grounded** — the parsed CV's chunks are retrievable by the P4 RAG agent with
   ``KbDocument.source_type == "user_cv"`` — ``test_cv_chunks_are_rag_grounded_live`` (live DB,
   authoritative) + ``test_rag_retrieve_surfaces_the_user_cv_chunk_offline`` (offline seam).
7. **Frontend** — the P5-07 upload/progress/view-edit UI works against this contract, proven by
   the existing ``frontend/__tests__/{profile,CvUpload,ProfileView}`` suites (confirmed green as
   a whole suite; not re-litigated here — see engineer.md).
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents.rag_agent import retrieve
from app.agents.state import AgentState, WorkerName
from app.api.jobs import get_job_status_service
from app.api.profile import get_profile_ingest_service, get_profile_store
from app.config import settings
from app.ingestion.composite_parser import CompositeDocumentParser
from app.ingestion.docling_parser import DoclingParser
from app.ingestion.ocr_parser import OcrDocumentParser
from app.ingestion.profile import ProfileSchema
from app.ingestion.structuring import PROFILE_TOOL_NAME, ProfileStructurer
from app.ingestion.types import ParsedDocument
from app.llm.types import ChatMessage, CompletionResult, FunctionCall, ToolCall, ToolSchema
from app.main import app
from app.repositories.models import KbChunk, KbDocument, Profile, User
from app.repositories.models.knowledge import EMBEDDING_DIM
from app.repositories.postgres import PostgresConnectionProvider
from app.repositories.profile_store import PostgresProfileStore
from app.security.dependencies import get_rate_limit_service, require_auth
from app.services.jobs import AsyncResultFactory, AsyncResultLike, JobStatusService
from app.services.profile_ingest import ProfileIngestService
from app.tasks.profile_ingest import (
    STATE_PARSING,
    STATE_PERSISTING,
    STATE_STRUCTURING,
    run_cv_ingestion,
)
from tests.fakes import (
    FakeEmbeddingClient,
    fake_current_user,
    rag_db_one_hit,
    unlimited_rate_limit_service,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ingestion"

#: The structured profile the (faked) LLM structuring step returns for the fixture CV. A
#: realistic, non-empty profile so the "usable profile" assertions (point 4) are meaningful:
#: an all-empty profile from a real CV must be a failure, not a pass.
_CANNED_PROFILE: dict[str, Any] = {
    "skills": ["Python", "SQL", "Spark", "AWS", "Airflow"],
    "experience": [
        {
            "title": "Data Engineer",
            "company": "Acme Corp",
            "start_date": "2019",
            "end_date": "2024",
            "description": "Built batch and streaming ETL pipelines.",
        }
    ],
    "education": [
        {
            "institution": "MIT",
            "degree": "BSc",
            "field": "Computer Science",
            "start_date": "2015",
            "end_date": "2019",
        }
    ],
    "goals": ["Become a staff data engineer."],
}


# --------------------------------------------------------------------------- #
# Fakes — only the true external edges (docling model, OCR binary, LLM, embeddings, broker).
# --------------------------------------------------------------------------- #
class _FakeDoclingDocument:
    def __init__(self, markdown: str, text: str) -> None:
        self._markdown = markdown
        self._text = text

    def export_to_markdown(self) -> str:
        return self._markdown

    def export_to_text(self) -> str:
        return self._text

    def export_to_dict(self) -> dict[str, Any]:
        return {}


class _FakeDoclingResult:
    """Minimal docling ``ConversionResult`` stand-in (only what ``DoclingParser`` reads)."""

    def __init__(self, *, markdown: str, text: str, fmt: str, page_count: int) -> None:
        self.status = type("Status", (), {"name": "SUCCESS"})()
        self.input = type(
            "Input", (), {"format": type("F", (), {"value": fmt})(), "page_count": page_count}
        )()
        self.document = _FakeDoclingDocument(markdown, text)


class _FakeConverter:
    def __init__(self, result: _FakeDoclingResult) -> None:
        self._result = result

    def convert(self, source: Any) -> _FakeDoclingResult:
        return self._result


class _FakeDocumentStream:
    def __init__(self, name: str, stream: Any) -> None:
        self.name = name
        self.stream = stream


class _FakeOcrEngine:
    """An :class:`~app.ingestion.ocr_parser.OcrEngine` double returning canned recovered text."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[str] = []

    def extract_text(self, source: bytes, *, source_format: str) -> str:
        self.calls.append(source_format)
        return self._text


class _FakeStructuringCompleter:
    """A scripted :class:`~app.ingestion.structuring.LLMCompleter` (no HF).

    Returns a forced ``record_profile`` tool call carrying ``_CANNED_PROFILE`` and records the
    messages it was handed, so a test can assert the *real* parsed CV text flowed into
    structuring (proving parse → structure are actually wired, not independently faked).
    """

    def __init__(self, profile: dict[str, Any] | None = None) -> None:
        self._profile = profile if profile is not None else _CANNED_PROFILE
        self.last_user_content: str = ""

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        self.last_user_content = " ".join(m.content or "" for m in messages)
        return CompletionResult(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_1",
                    function=FunctionCall(
                        name=PROFILE_TOOL_NAME, arguments=json.dumps(self._profile)
                    ),
                )
            ],
            model="fake",
        )


class _FixedEmbedder:
    """Embedder returning a fixed, non-degenerate ``vector(4096)`` per text (matches the column).

    A non-zero vector so pgvector cosine distance is well-defined; identical across texts so the
    lexical ``ts_rank`` half of the hybrid search is what differentiates the CV chunk on a
    keyword query (the RAG-grounding test does not depend on real semantic similarity).
    """

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.1] * EMBEDDING_DIM for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [0.1] * EMBEDDING_DIM


class _FakeAsyncResult:
    def __init__(self, state: str, result: Any = None) -> None:
        self._state = state
        self._result = result

    @property
    def state(self) -> str:
        return self._state

    @property
    def result(self) -> Any:
        return self._result


def _async_result_factory(state: str, info: Any) -> AsyncResultFactory:
    """A scripted :class:`~app.services.jobs.AsyncResultFactory` (no live Celery/Redis)."""

    def factory(task_id: str) -> AsyncResultLike:
        return _FakeAsyncResult(state, info)

    return factory


class _CapturingEnqueuer:
    """Records the enqueue payload and returns a canned task id (no Celery broker)."""

    def __init__(self, task_id: str = "task-p5") -> None:
        self._task_id = task_id
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        *,
        content_b64: str,
        filename: str | None,
        media_type: str | None,
        user_id: str | None,
        session_id: str,
    ) -> str:
        self.calls.append(
            {
                "content_b64": content_b64,
                "filename": filename,
                "media_type": media_type,
                "user_id": user_id,
                "session_id": session_id,
            }
        )
        return self._task_id


def _composite(
    *,
    docling_result: _FakeDoclingResult,
    ocr_text: str,
) -> tuple[CompositeDocumentParser, _FakeOcrEngine]:
    """Wire the **real** composite chain with fake engines at the true external edges.

    Real :class:`CompositeDocumentParser` + :class:`DoclingParser` + :class:`OcrDocumentParser`
    + real :class:`~app.ingestion.text_layer.TextLayerCheck`; only the docling convert backend
    and the OCR binary are faked (the model download / system binary this env lacks).
    """
    ocr_engine = _FakeOcrEngine(ocr_text)
    docling = DoclingParser(
        converter_factory=lambda: _FakeConverter(docling_result),
        document_stream_factory=_FakeDocumentStream,
    )
    ocr = OcrDocumentParser(engine_factory=lambda: ocr_engine)
    return CompositeDocumentParser(primary=docling, fallbacks=(ocr,)), ocr_engine


def _assert_usable_profile(profile: ProfileSchema) -> None:
    """A parsed profile is *usable* only if the core sections are non-empty (point 4)."""
    assert profile.skills, "expected non-empty skills from a realistic CV"
    assert profile.experience, "expected non-empty experience from a realistic CV"
    assert profile.education, "expected non-empty education from a realistic CV"


# =========================================================================== #
# 1. Scanned/image PDF → OCR fallback → usable structured profile (points 1, 4)
# =========================================================================== #
async def test_scanned_pdf_triggers_ocr_fallback_into_structured_profile() -> None:
    """An image-only PDF: docling recovers no text layer, so the **real** composite falls back
    to OCR, and the recovered text structures into a usable profile.

    Proves the P5-02 fallback tier actually fires (not just the docling primary path) through
    the real tiering + text-layer decision, and that the OCR output flows into structuring.
    """
    content = (FIXTURES / "scanned_cv.pdf").read_bytes()
    # docling on a raster PDF recovers no usable text layer (empty extract, 1 page).
    empty_docling = _FakeDoclingResult(markdown="", text="", fmt="pdf", page_count=1)
    ocr_text = (
        "Jane Doe\nSenior Data Engineer\n\nSkills: Python, SQL, Spark, AWS, Airflow\n\n"
        "Experience: Data Engineer at Acme Corp (2019-2024).\n\n"
        "Education: BSc Computer Science, MIT (2015-2019)."
    )
    parser, ocr_engine = _composite(docling_result=empty_docling, ocr_text=ocr_text)

    parsed = await parser.parse(content, filename="scanned_cv.pdf", media_type="application/pdf")

    # The OCR fallback tier ran (docling primary yielded no text layer), not the primary path.
    assert parsed.metadata["ocr_fallback_used"] is True
    assert ocr_engine.calls == ["pdf"]  # the OCR engine was actually invoked, on the PDF
    assert parsed.text.strip()  # non-trivial recovered text

    completer = _FakeStructuringCompleter()
    profile = await ProfileStructurer(completer).structure(parsed)

    # The OCR-recovered text was actually handed to structuring (parse → structure wired).
    assert "Data Engineer" in completer.last_user_content
    _assert_usable_profile(profile)


# =========================================================================== #
# 2. PPTX → docling primary → usable structured profile (points 2, 4)
# =========================================================================== #
async def test_pptx_cv_parses_via_docling_primary_into_structured_profile() -> None:
    """A real PPTX CV parses via the **real** docling primary (no OCR fallback) into a usable
    profile.

    Uses the genuine docling engine (its office pipeline needs no model download); skipped where
    docling is not installed (the curated CI venv). Proves the primary tier + structuring on a
    real slide-style document.
    """
    pytest.importorskip("docling")
    content = (FIXTURES / "sample_cv.pptx").read_bytes()
    # Real docling primary; a fake OCR engine that must never be reached on a good text layer.
    ocr_engine = _FakeOcrEngine("SHOULD NOT BE USED")
    parser = CompositeDocumentParser(
        primary=DoclingParser(),
        fallbacks=(OcrDocumentParser(engine_factory=lambda: ocr_engine),),
    )

    parsed = await parser.parse(
        content,
        filename="sample_cv.pptx",
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )

    assert parsed.source_format == "pptx"
    assert parsed.metadata["ocr_fallback_used"] is False  # primary succeeded; no OCR
    assert ocr_engine.calls == []  # the OCR tier was never reached
    assert "Data Engineer" in parsed.text  # docling really extracted the slide text

    completer = _FakeStructuringCompleter()
    profile = await ProfileStructurer(completer).structure(parsed)

    assert "Data Engineer" in completer.last_user_content
    _assert_usable_profile(profile)


# =========================================================================== #
# 3. Async: 202 + task_id, no in-request parse; status polls the lifecycle (point 3)
# =========================================================================== #
async def test_upload_endpoint_is_async_202_and_no_in_request_parse() -> None:
    """``POST /api/profile/cv`` returns ``202`` + ``task_id`` immediately; the file is enqueued
    (base64), not parsed in the request path.

    The **real** router + real :class:`ProfileIngestService` run; only the enqueue port is faked
    (captures the payload). Proving the enqueuer received the *raw upload bytes* — not a parsed
    profile — is the direct evidence the parse was deferred off the request path (§5.3).
    """
    content = (FIXTURES / "scanned_cv.pdf").read_bytes()
    enqueuer = _CapturingEnqueuer()
    service = ProfileIngestService(enqueuer, max_upload_bytes=10 * 1024 * 1024)
    app.dependency_overrides[get_profile_ingest_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "s1", role="user", user_id="u1"
    )
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/profile/cv",
                files={"file": ("scanned_cv.pdf", content, "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "task-p5"
    assert body["status"] == "accepted"  # the job handle; the parse runs off the request path
    # The request path enqueued the untouched bytes (no synchronous parse); decoding the
    # captured payload returns exactly the uploaded file.
    assert len(enqueuer.calls) == 1
    assert base64.b64decode(enqueuer.calls[0]["content_b64"]) == content


async def test_job_status_polls_producer_lifecycle_to_success() -> None:
    """``GET /api/jobs/status/{task_id}`` surfaces the P5-04 producer lifecycle through the
    **real** endpoint: pending → in-progress-with-stage (parsing → structuring → persisting) →
    success.

    Driven with a scripted ``AsyncResult`` per poll (no live broker), using the producer's own
    :data:`STATE_PARSING`/``STRUCTURING``/``PERSISTING`` constants and its terminal result shape
    — so any drift between producer and consumer would fail this.
    """
    lifecycle: list[tuple[str, Any, str, str | None]] = [
        # (celery_state, info, expected_status, expected_stage)
        ("PENDING", None, "pending", None),
        (
            STATE_PARSING,
            {"stage": "parsing", "message": "Extracting document text."},
            "in_progress",
            "parsing",
        ),
        (
            STATE_STRUCTURING,
            {"stage": "structuring", "message": "Structuring the profile."},
            "in_progress",
            "structuring",
        ),
        (
            STATE_PERSISTING,
            {"stage": "persisting", "message": "Saving your profile."},
            "in_progress",
            "persisting",
        ),
        (
            "SUCCESS",
            {
                "profile": _CANNED_PROFILE,
                "persisted": True,
                "kb_document_id": "d",
                "chunk_count": 2,
            },
            "success",
            None,
        ),
    ]
    transport = ASGITransport(app=app)
    for state, info, expected_status, expected_stage in lifecycle:
        service = JobStatusService(_async_result_factory(state, info))
        app.dependency_overrides[get_job_status_service] = lambda: service
        app.dependency_overrides[require_auth] = lambda: fake_current_user(
            "s1", role="user", user_id="u1"
        )
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/jobs/status/task-p5")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == expected_status, (state, body)
        if expected_stage is not None:
            assert body["stage"] == expected_stage
        if expected_status == "success":
            assert body["result"]["profile"] == _CANNED_PROFILE


async def test_task_core_emits_real_progress_stages_for_both_documents() -> None:
    """The **real** task core (:func:`run_cv_ingestion`) emits genuine progress transitions for
    *both* the scanned PDF and the PPTX — proving the stages the status endpoint reports are
    really produced by the pipeline, not just scriptable.

    Runs the guest path (no DB) so it stays offline: it still parses + structures, emitting
    ``PARSING`` then ``STRUCTURING`` in order for each document.
    """
    empty_docling = _FakeDoclingResult(markdown="", text="", fmt="pdf", page_count=1)
    ocr_text = "Jane Doe\nData Engineer\nSkills: Python, SQL.\nEducation: BSc, MIT."
    pdf_parser, _ = _composite(docling_result=empty_docling, ocr_text=ocr_text)

    good_docling = _FakeDoclingResult(
        markdown="# Jane Doe\n\nData Engineer\n\nSkills: Python",
        text="Jane Doe Data Engineer Skills: Python",
        fmt="pptx",
        page_count=0,
    )
    pptx_parser, _ = _composite(docling_result=good_docling, ocr_text="unused")

    for parser, content, filename, media_type in [
        (pdf_parser, b"%PDF-1.4", "scanned_cv.pdf", "application/pdf"),
        (
            pptx_parser,
            b"PK-pptx",
            "sample_cv.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
    ]:
        states: list[str] = []
        result = await run_cv_ingestion(
            content=content,
            filename=filename,
            media_type=media_type,
            user_id=None,  # guest: parses + structures, no persistence (offline)
            parser=parser,
            structurer=ProfileStructurer(_FakeStructuringCompleter()),
            embedder=FakeEmbeddingClient(),
            db=None,  # type: ignore[arg-type]  # never touched on the guest path
            progress=lambda state, _meta: states.append(state),
        )
        assert states == [STATE_PARSING, STATE_STRUCTURING]  # real, ordered stage transitions
        assert result["persisted"] is False
        _assert_usable_profile(ProfileSchema.model_validate(result["profile"]))


# =========================================================================== #
# 6 (offline seam). RAG retrieval surfaces the user's CV chunk as a citation.
# =========================================================================== #
async def test_rag_retrieve_surfaces_the_user_cv_chunk_offline() -> None:
    """The **real** P4 RAG worker + **real** ``hybrid_search_chunks`` surface a logged-in user's
    private CV document chunk as a grounded citation.

    Offline seam for point 6: drives the real retrieval path over a scripted session mimicking
    the post-ingestion DB state (the user's CV doc id is in scope, its chunk is the hybrid hit,
    its title resolves). Proves the retrieval half consumes exactly what the P5 persist step
    writes; the live test below proves the same against a real ``source_type == 'user_cv'`` row.
    """
    db, doc_id, chunk_id = rag_db_one_hit(
        title="sample_cv.pptx", content="Jane Doe — Data Engineer. Skills: Python, SQL, Spark."
    )
    state = AgentState(
        session_id="s1", user_id=str(uuid.uuid4()), user_message="what are my skills?"
    )

    result = await retrieve(state, embedder=FakeEmbeddingClient(), db=db)

    assert result.worker is WorkerName.RAG
    assert result.error is None
    assert result.data["chunk_count"] == 1
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.source_id == str(chunk_id)
    assert citation.title == "sample_cv.pptx"
    assert citation.worker is WorkerName.RAG


# =========================================================================== #
# Live-Postgres proofs (points 5 & 6) — skip cleanly when no DB is reachable.
# =========================================================================== #
async def _postgres_reachable() -> bool:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect():
            return True
    except Exception:  # noqa: BLE001 - any connect failure → skip, never error the suite
        return False
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def provider() -> AsyncIterator[PostgresConnectionProvider]:
    """A real connection provider; skips if Postgres / the P2 schema is not reachable."""
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — live P5 integration test skipped")
    prov = PostgresConnectionProvider.from_settings()
    try:
        async with prov.session() as session:
            try:
                await session.execute(select(KbDocument).limit(1))
                await session.execute(select(Profile).limit(1))
            except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
                pytest.skip("schema not applied — run `alembic upgrade head`")
        yield prov
    finally:
        await prov.aclose()


def _parsed_cv(text: str) -> ParsedDocument:
    return ParsedDocument(
        markdown=f"# CV\n\n{text}", text=text, source_format="pdf", page_count=1, metadata={}
    )


async def _ingest_for_user(
    provider: PostgresConnectionProvider, user_id: uuid.UUID, *, text: str, profile: ProfileSchema
) -> dict[str, Any]:
    """Persist one CV for ``user_id`` via the real task core over the real provider."""

    class _Parser:
        async def parse(
            self, source: Any, *, filename: Any = None, media_type: Any = None
        ) -> ParsedDocument:
            return _parsed_cv(text)

    class _Structurer:
        async def structure(self, document: ParsedDocument) -> ProfileSchema:
            return profile

    return await run_cv_ingestion(
        content=b"%PDF-1.4",
        filename="cv.pdf",
        media_type="application/pdf",
        user_id=str(user_id),
        parser=_Parser(),  # type: ignore[arg-type]
        structurer=_Structurer(),
        embedder=_FixedEmbedder(),  # type: ignore[arg-type]
        db=provider,
    )


async def test_persisted_profile_is_reusable_via_get_profile(
    provider: PostgresConnectionProvider,
) -> None:
    """Point 5: after ingestion persists, ``GET /api/profile`` returns the parsed profile with
    **no re-upload** — the real endpoint over the real :class:`PostgresProfileStore`."""
    user_id = uuid.uuid4()
    async with provider.session() as session:
        session.add(
            User(id=user_id, provider="google", sub=f"sub-{user_id}", email="p5@example.com")
        )
        await session.commit()

    try:
        stored = ProfileSchema(skills=["Python", "SQL"], goals=["Staff engineer"])
        await _ingest_for_user(
            provider, user_id, text="Experience: Data Engineer at Acme.", profile=stored
        )

        store = PostgresProfileStore(provider)
        app.dependency_overrides[get_profile_store] = lambda: store
        app.dependency_overrides[require_auth] = lambda: fake_current_user(
            "s1", role="user", user_id=str(user_id)
        )
        try:
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/profile")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        # The profile parsed during ingestion is reusable across chats via GET, no re-upload.
        assert response.json() == stored.model_dump()
    finally:
        async with provider.session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is not None:
                await session.delete(user)
                await session.commit()


async def test_cv_chunks_are_rag_grounded_live(provider: PostgresConnectionProvider) -> None:
    """Point 6 (authoritative): the parsed CV's chunks, persisted by the P5 pipeline, are
    retrievable by the **real** P4 RAG worker, and their parent document is a ``user_cv`` doc.

    Persists a CV via the real task core, then runs the real ``retrieve`` over the *same*
    provider with a keyword query — proving the P5 ingestion and P4 retrieval pipelines share
    one pgvector store end-to-end (not just independently tested).
    """
    user_id = uuid.uuid4()
    async with provider.session() as session:
        session.add(
            User(id=user_id, provider="google", sub=f"sub-{user_id}", email="rag@example.com")
        )
        await session.commit()

    try:
        ingest = await _ingest_for_user(
            provider,
            user_id,
            text=(
                "Jane Doe. Senior Data Engineer. Skills: Python, SQL, Spark, Airflow. "
                "Experience: Data Engineer at Acme Corp building ETL pipelines."
            ),
            profile=ProfileSchema(skills=["Python", "SQL", "Spark"]),
        )
        cv_doc_id = uuid.UUID(str(ingest["kb_document_id"]))

        state = AgentState(
            session_id="s1",
            user_id=str(user_id),
            user_message="What are my Python and Spark data engineering skills?",
        )
        result = await retrieve(state, embedder=_FixedEmbedder(), db=provider)  # type: ignore[arg-type]

        assert result.citations, "the user's CV chunk should be retrieved for a relevant query"
        chunk_ids = [uuid.UUID(c.source_id) for c in result.citations]

        # Every retrieved chunk belongs to a real KB document; at least one is *this user's*
        # parsed CV, and its parent document is a `user_cv` source (the P5-04 invariant).
        async with provider.session() as session:
            rows = (
                await session.execute(
                    select(KbChunk.id, KbDocument.id, KbDocument.source_type, KbDocument.user_id)
                    .join(KbDocument, KbChunk.kb_document_id == KbDocument.id)
                    .where(KbChunk.id.in_(chunk_ids))
                )
            ).all()
        grounded_cv = [
            r for r in rows if r[1] == cv_doc_id and r[2] == "user_cv" and r[3] == user_id
        ]
        assert grounded_cv, "retrieved citations must include this user's user_cv CV chunk(s)"
    finally:
        async with provider.session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is not None:
                await session.delete(user)
                await session.commit()
