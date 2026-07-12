"""Live-Postgres integration test for CV-ingestion persistence (P5-04, §5.1).

Proves :func:`~app.tasks.profile_ingest.run_cv_ingestion` persists correctly against the
**real** P2-03/P2-04 schema: a :class:`Profile` row is upserted and exactly one
``KbDocument(source_type="user_cv")`` + its embedded ``KbChunk`` rows are written for the
user — and that a **re-upload** replaces the prior CV document (still exactly one) and updates
the profile in place. This needs the real ``vector(4096)`` + JSONB columns, so (like
``test_vector_search.py``) it runs against the docker-compose Postgres and **skips cleanly**
when no DB / the schema is unreachable.

Parser / structurer / embedder are controlled fakes (no docling / HF / 8B model); only the DB
is real. The test creates its own :class:`User`, runs the real (committing) pipeline over a
real :class:`PostgresConnectionProvider`, asserts, and cleans up by deleting the user (cascade
removes the profile + CV document + chunks), leaving the database as it was found.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.ingestion.profile import ProfileSchema
from app.ingestion.types import ParsedDocument
from app.repositories.models import KbChunk, KbDocument, Profile, User
from app.repositories.models.knowledge import EMBEDDING_DIM
from app.repositories.postgres import PostgresConnectionProvider
from app.tasks.profile_ingest import run_cv_ingestion
from tests.test_profile_ingest_task import FakeParser, FakeStructurer


async def _postgres_reachable() -> bool:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect():
            return True
    except Exception:  # noqa: BLE001 - any connect failure → skip, never error the suite
        return False
    finally:
        await engine.dispose()


class _FixedEmbedder:
    """Embedder returning a valid 4096-dim vector per chunk (matches the real column width)."""

    async def embed_documents(self, texts: Any) -> list[list[float]]:
        return [[0.0] * EMBEDDING_DIM for _ in texts]

    async def embed_query(self, text: str) -> list[float]:  # pragma: no cover - unused here
        return [0.0] * EMBEDDING_DIM


@pytest_asyncio.fixture
async def provider() -> AsyncIterator[PostgresConnectionProvider]:
    """A real connection provider; skips if Postgres / the schema is not reachable."""
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — integration test skipped")
    prov = PostgresConnectionProvider.from_settings()
    try:
        async with prov.session() as session:
            try:
                await session.execute(select(KbDocument).limit(1))
                await session.execute(select(Profile).limit(1))
            except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
                pytest.skip(
                    "schema (migrations 0002/0003) not applied — run `alembic upgrade head`"
                )
        yield prov
    finally:
        await prov.aclose()


def _doc(text: str) -> ParsedDocument:
    return ParsedDocument(
        markdown=f"# CV\n\n{text}", text=text, source_format="pdf", page_count=1, metadata={}
    )


async def _count_cv_docs(provider: PostgresConnectionProvider, user_id: uuid.UUID) -> int:
    async with provider.session() as session:
        result = await session.execute(
            select(func.count())
            .select_from(KbDocument)
            .where(KbDocument.user_id == user_id, KbDocument.source_type == "user_cv")
        )
        return int(result.scalar_one())


async def test_ingestion_persists_and_reupload_replaces(
    provider: PostgresConnectionProvider,
) -> None:
    user_id = uuid.uuid4()
    async with provider.session() as session:
        session.add(
            User(id=user_id, provider="google", sub=f"sub-{user_id}", email="cv@example.com")
        )
        await session.commit()

    try:
        # --- First upload: creates profile + one CV document + chunks. ---
        await run_cv_ingestion(
            content=b"%PDF-1.4",
            filename="cv.pdf",
            media_type="application/pdf",
            user_id=str(user_id),
            parser=FakeParser(_doc("Experience: Data Engineer at Acme.")),
            structurer=FakeStructurer(ProfileSchema(skills=["Python"])),
            embedder=_FixedEmbedder(),  # type: ignore[arg-type]
            db=provider,
        )

        async with provider.session() as session:
            profile = (
                await session.execute(select(Profile).where(Profile.user_id == user_id))
            ).scalar_one()
            assert profile.data == {
                "skills": ["Python"],
                "experience": [],
                "education": [],
                "goals": [],
            }
            doc = (
                await session.execute(select(KbDocument).where(KbDocument.user_id == user_id))
            ).scalar_one()
            assert doc.source_type == "user_cv"
            chunk_count = (
                await session.execute(
                    select(func.count())
                    .select_from(KbChunk)
                    .where(KbChunk.kb_document_id == doc.id)
                )
            ).scalar_one()
            assert chunk_count >= 1

        assert await _count_cv_docs(provider, user_id) == 1

        # --- Re-upload: profile updated in place, still exactly one CV document. ---
        await run_cv_ingestion(
            content=b"%PDF-1.4 v2",
            filename="cv_v2.pdf",
            media_type="application/pdf",
            user_id=str(user_id),
            parser=FakeParser(_doc("Experience: Senior Data Engineer at Beta.")),
            structurer=FakeStructurer(ProfileSchema(skills=["Python", "Rust"])),
            embedder=_FixedEmbedder(),  # type: ignore[arg-type]
            db=provider,
        )

        assert await _count_cv_docs(provider, user_id) == 1
        async with provider.session() as session:
            profile = (
                await session.execute(select(Profile).where(Profile.user_id == user_id))
            ).scalar_one()
            assert profile.data["skills"] == ["Python", "Rust"]
            doc = (
                await session.execute(select(KbDocument).where(KbDocument.user_id == user_id))
            ).scalar_one()
            assert doc.title == "cv_v2.pdf"
    finally:
        # Cascade-clean: deleting the user removes profile + CV document + chunks.
        async with provider.session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is not None:
                await session.delete(user)
                await session.commit()
