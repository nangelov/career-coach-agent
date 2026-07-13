"""Celery CV-ingestion task — parse → structure → persist profile + pgvector chunks (§5.1/§5.3).

The producer side of the async document-intelligence pipeline. ``POST /api/profile/cv``
(:mod:`app.api.profile`) enqueues :func:`ingest_cv`; this worker task then runs the full
P5-01→P5-03 chain end-to-end off the request path (§5.3: *"slow document intelligence runs as
a Celery background job with progress surfaced to the UI"*):

1. :class:`~app.ingestion.composite_parser.CompositeDocumentParser` — layout-aware extract
   (docling primary, OCR fallback).
2. :class:`~app.ingestion.structuring.ProfileStructurer` — LLM-assisted structuring →
   :class:`~app.ingestion.profile.ProfileSchema`.
3. **Persist** — upsert ``profiles.data`` (JSONB) and write one
   ``KbDocument(source_type="user_cv")`` + its embedded ``KbChunk`` rows into pgvector
   (§5.1 end state: *"embed chunks → pgvector; profile JSONB → Postgres"*).

**Progress = Celery's own state machinery (Redis-backed), no bespoke channel.** The task is
``bind=True`` and calls :meth:`self.update_state` with the coarse stages
(:data:`STATE_PARSING` → :data:`STATE_STRUCTURING` → :data:`STATE_PERSISTING`). Because the
Celery result backend *is* Redis (``celery_app`` ``backend=settings.REDIS_URL``), this already
satisfies "progress via Redis" — P5-06's ``GET /api/jobs/status/{task_id}`` reads exactly this
state + meta. Introducing a second progress store would duplicate what Celery gives for free.

**Sync task, async stack — the bridge.** Celery tasks are synchronous, but the DB/embedding
stack is async-only (:class:`~app.repositories.postgres.PostgresConnectionProvider` is
``AsyncEngine``-based, :meth:`EmbeddingClient.embed_documents` is a coroutine). The task body
therefore wraps an async implementation in :func:`asyncio.run`. It also constructs its **own**
parser / LLM router / embedder / Postgres provider **inside the worker process** — a Celery
worker does not share the FastAPI ``app.state`` composition root, so it wires its own
(mirroring :mod:`app.bootstrap`'s lazy posture, adapted for a standalone worker) and closes
them when the task ends. All heavy imports are deferred into the builder so importing this
module (e.g. by the API composition root, for :func:`enqueue_cv_ingest`) stays light and needs
no ML stack.

**Guest handling.** A guest (``user_id=None``) has no ``users`` row to anchor a ``Profile`` /
private ``KbDocument`` (FK-required), and guests get no persisted history (§4). So the task
still parses + structures (progress + result observable), but **skips Postgres persistence**
for a guest — the structured profile is returned in the task result for preview only.

**Errors are not swallowed.** An unrecoverable parse/structuring failure surfaces as the single
:class:`~app.ingestion.parser.DocumentParseError` /
:class:`~app.ingestion.profile.ProfileStructuringError`, which propagates out of the task so
Celery records a ``FAILURE`` state carrying the error message (consumed by P5-06).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, cast

from sqlalchemy import delete, select

from app.config import settings
from app.ingestion.chunking import chunk_text
from app.ingestion.profile import ProfileSchema
from app.repositories.models.identity import Profile
from app.repositories.models.knowledge import KbDocument
from app.repositories.postgres import PostgresConnectionProvider
from app.repositories.vector_search import add_kb_chunk
from app.tasks.celery_app import celery_app

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.ingestion.parser import DocumentParser
    from app.ingestion.types import ParsedDocument
    from app.llm.embeddings import EmbeddingClient

logger = logging.getLogger(__name__)

#: Celery custom states surfaced during the ingest (Redis-backed via the result backend).
#: P5-06's status endpoint reports these verbatim. Kept distinct from Celery's built-in
#: PENDING/SUCCESS/FAILURE so a poller can show a meaningful "what is it doing now?" stage.
STATE_PARSING = "PARSING"
STATE_STRUCTURING = "STRUCTURING"
STATE_PERSISTING = "PERSISTING"

#: The literal ``KbDocument.source_type`` for a user's parsed CV (§5.1). Matches the
#: ``ck_kb_documents_source_type`` check constraint value.
CV_SOURCE_TYPE = "user_cv"


# --------------------------------------------------------------------------- #
# Injected-collaborator ports (structural — real impls satisfy them; tests fake them)
# --------------------------------------------------------------------------- #
class CvStructurer(Protocol):
    """The structuring capability :func:`run_cv_ingestion` needs (real ProfileStructurer)."""

    async def structure(self, document: ParsedDocument) -> ProfileSchema: ...


class SessionProvider(Protocol):
    """The DB-session capability :func:`run_cv_ingestion` needs (the real Postgres provider)."""

    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


async def run_cv_ingestion(
    *,
    content: bytes,
    filename: str | None,
    media_type: str | None,
    user_id: str | None,
    parser: DocumentParser,
    structurer: CvStructurer,
    embedder: EmbeddingClient,
    db: SessionProvider,
    progress: Callable[[str, dict[str, Any]], None] = lambda _state, _meta: None,
) -> dict[str, Any]:
    """Run the full parse → structure → persist pipeline; return the task result payload.

    The **injected**, testable core of the task (no Celery/broker required): all collaborators
    are passed in, so a unit test drives it with fakes and no real docling/HF/Postgres. The
    Celery task body (:func:`ingest_cv`) is the thin production wiring that builds the real
    collaborators and calls this.

    Persists only for a logged-in user (``user_id`` set); a guest's result is returned but not
    written (see the module docstring). ``progress(state, meta)`` is invoked at each stage —
    the task wires it to :meth:`Celery.Task.update_state` (Redis-backed).

    Returns a JSON-serializable dict — the Celery task's result (consumed by P5-06):
    ``{"profile", "persisted", "kb_document_id", "chunk_count"}``.

    Raises:
        DocumentParseError: the document could not be parsed (propagates → Celery FAILURE).
        ProfileStructuringError: structuring failed unrecoverably (propagates → FAILURE).
    """
    progress(STATE_PARSING, {"stage": "parsing", "message": "Extracting document text."})
    parsed = await parser.parse(content, filename=filename, media_type=media_type)

    progress(
        STATE_STRUCTURING,
        {"stage": "structuring", "message": "Structuring the profile from the CV."},
    )
    profile = await structurer.structure(parsed)

    chunks = chunk_text(parsed.text or parsed.markdown)
    result: dict[str, Any] = {
        "profile": profile.model_dump(),
        "persisted": False,
        "kb_document_id": None,
        "chunk_count": len(chunks),
    }
    if user_id is None:
        # Guest: no users row to anchor a profile/private KB doc (§4). Parse result is
        # returned for preview only; nothing is written to Postgres.
        return result

    progress(
        STATE_PERSISTING,
        {"stage": "persisting", "message": "Saving your profile and indexing your CV."},
    )
    embeddings = await embedder.embed_documents(chunks) if chunks else []
    kb_document_id = await _persist_profile_and_chunks(
        db,
        user_id=uuid.UUID(user_id),
        profile=profile,
        parsed=parsed,
        chunks=chunks,
        embeddings=embeddings,
        filename=filename,
    )
    result["persisted"] = True
    result["kb_document_id"] = str(kb_document_id)
    return result


async def _persist_profile_and_chunks(
    db: SessionProvider,
    *,
    user_id: uuid.UUID,
    profile: ProfileSchema,
    parsed: ParsedDocument,
    chunks: Sequence[str],
    embeddings: Sequence[Sequence[float]],
    filename: str | None,
) -> uuid.UUID:
    """Upsert the profile JSONB and (re)write the user's ``user_cv`` KB document + chunks.

    Runs in one transaction (§8 layering — the repository/session owns the DB, the task owns
    the boundary): upsert ``profiles.data`` (one row per user), replace any prior ``user_cv``
    document (so re-upload leaves **exactly one**, its chunks removed by the FK cascade), then
    insert the fresh document and its embedded chunks via the existing
    :func:`~app.repositories.vector_search.add_kb_chunk` helper. Returns the new document id.
    """
    async with db.session() as session:
        # --- Upsert the structured profile (one row per user, unique on user_id). ---
        existing_profile = (
            await session.execute(select(Profile).where(Profile.user_id == user_id))
        ).scalar_one_or_none()
        profile_data = profile.model_dump()
        if existing_profile is None:
            session.add(Profile(user_id=user_id, data=profile_data))
        else:
            existing_profile.data = profile_data

        # --- Replace any prior CV document (keep exactly one user_cv doc per user). ---
        # Bulk delete; child kb_chunks are removed by the ON DELETE CASCADE FK.
        await session.execute(
            delete(KbDocument).where(
                KbDocument.user_id == user_id,
                KbDocument.source_type == CV_SOURCE_TYPE,
            )
        )
        document = KbDocument(
            title=filename or "CV",
            source="user-cv",
            source_type=CV_SOURCE_TYPE,
            user_id=user_id,
            content=parsed.text or None,
            meta={
                "source_format": parsed.source_format,
                "page_count": parsed.page_count,
                "ocr_fallback_used": parsed.metadata.get("ocr_fallback_used"),
            },
        )
        session.add(document)
        await session.flush()  # populate document.id for the chunk FKs

        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            await add_kb_chunk(
                session,
                kb_document_id=document.id,
                chunk_index=index,
                content=chunk,
                embedding=embedding,
                meta={"source_format": parsed.source_format},
            )

        await session.commit()
        return document.id


async def _ingest_cv_entrypoint(
    *,
    content: bytes,
    filename: str | None,
    media_type: str | None,
    user_id: str | None,
    progress: Callable[[str, dict[str, Any]], None],
) -> dict[str, Any]:
    """Build the worker-local collaborators, run the pipeline, and release resources.

    This is the standalone-worker composition root for CV ingestion: a Celery worker does not
    share the FastAPI ``app.state``, so it constructs its own parser / LLM router / embedder /
    Postgres provider here (heavy imports deferred to keep module import light) and disposes
    the Postgres pool and Redis client when the task ends.
    """
    from redis.asyncio import Redis  # noqa: PLC0415 - deferred worker-only dependency

    from app.ingestion.composite_parser import build_default_composite_parser  # noqa: PLC0415
    from app.ingestion.structuring import ProfileStructurer  # noqa: PLC0415
    from app.llm.embeddings import SentenceTransformerEmbeddingClient  # noqa: PLC0415
    from app.llm.router import LLMRouter, RedisLike  # noqa: PLC0415

    redis_client: Redis | None = None
    db: PostgresConnectionProvider | None = None
    try:
        # Construct inside the try so a failure part-way through still closes whatever was
        # already opened (e.g. redis_client) in the finally — no leaked connections/pools.
        parser = build_default_composite_parser()
        redis_client = Redis.from_url(settings.REDIS_URL)
        router = LLMRouter.from_settings(settings, redis_client=cast("RedisLike", redis_client))
        structurer = ProfileStructurer(router)
        embedder = SentenceTransformerEmbeddingClient()
        db = PostgresConnectionProvider.from_settings()
        return await run_cv_ingestion(
            content=content,
            filename=filename,
            media_type=media_type,
            user_id=user_id,
            parser=parser,
            structurer=structurer,
            embedder=embedder,
            db=db,
            progress=progress,
        )
    finally:
        if db is not None:
            await db.aclose()
        if redis_client is not None:
            await redis_client.aclose()


@celery_app.task(bind=True, name="tasks.ingest_cv")
def ingest_cv(
    self: Any,
    *,
    content_b64: str,
    filename: str | None,
    media_type: str | None,
    user_id: str | None,
    session_id: str,
) -> dict[str, Any]:
    """Celery entry: parse an uploaded CV → structured profile + pgvector chunks (§5.1/§5.3).

    Sync task body: decodes the base64 upload (the JSON serializer cannot carry raw bytes),
    bridges to the async pipeline via :func:`asyncio.run`, and reports progress through
    Celery's own Redis-backed state machinery. An unrecoverable parse/structuring error
    propagates so Celery records ``FAILURE`` with the message (not swallowed — P5-06 reads it).
    """
    content = base64.b64decode(content_b64)

    def progress(state: str, meta: dict[str, Any]) -> None:
        self.update_state(state=state, meta=dict(meta))

    try:
        return asyncio.run(
            _ingest_cv_entrypoint(
                content=content,
                filename=filename,
                media_type=media_type,
                user_id=user_id,
                progress=progress,
            )
        )
    except Exception:
        # Let Celery mark FAILURE (message preserved); log for the worker operator.
        logger.warning("CV ingestion task failed for session %s", session_id, exc_info=True)
        raise


def enqueue_cv_ingest(
    *,
    content_b64: str,
    filename: str | None,
    media_type: str | None,
    user_id: str | None,
    session_id: str,
) -> str:
    """Enqueue :func:`ingest_cv` on the broker; return the task id (the P5-06 poll handle).

    The production :class:`~app.services.profile_ingest.CvIngestEnqueuer` the composition root
    wires into :class:`~app.services.profile_ingest.ProfileIngestService`. Kept as a plain
    function (not a method) so the service depends only on the narrow callable port, never on
    Celery.
    """
    async_result = ingest_cv.apply_async(
        kwargs={
            "content_b64": content_b64,
            "filename": filename,
            "media_type": media_type,
            "user_id": user_id,
            "session_id": session_id,
        }
    )
    return str(async_result.id)
