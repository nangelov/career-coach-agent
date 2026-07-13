"""Integration checks for :class:`PostgresAccountRepository` against **real Postgres** (SEC-05).

Proves the GDPR erasure/export adapter over the actual schema:

* ``export`` returns every one of a user's own rows across the whole footprint, is **strictly
  scoped** to that user (never another user's rows, never shared ``user_id IS NULL`` KB rows),
  and **excludes raw embedding vectors** (§7.6).
* ``delete_user`` **cascades** — after it, none of the user's rows survive in any table, while a
  second user's data and the shared KB document are untouched; and it scrubs the ``contact`` PII
  from the SET-NULL-detached ``feedback`` row so the surviving product feedback is anonymized.

Requires the docker-compose Postgres (JSONB/UUID/pgvector types SQLite cannot represent). The
suite **skips automatically** when no Postgres is reachable at ``DATABASE_URL`` so free-tier CI
without a DB stays green. Each test erases the throwaway users it created (the same cascade
under test), leaving the DB as found.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.repositories.account import PostgresAccountRepository
from app.repositories.models.dashboard import (
    DashboardTask,
    Goal,
    Milestone,
    Pdp,
    ProgressEntry,
)
from app.repositories.models.identity import (
    Conversation,
    Feedback,
    Message,
    MessageFeedback,
    Preference,
    Profile,
    Session,
    User,
)
from app.repositories.models.knowledge import EMBEDDING_DIM, KbChunk, KbDocument, UserMemory
from app.repositories.postgres import PostgresConnectionProvider

_EMBED = [0.1] * EMBEDDING_DIM


def _owned(model: Any, uid: uuid.UUID) -> Any:
    """A ``COUNT(*)`` select over ``model`` rows directly owned by user ``uid``."""
    return select(func.count()).select_from(model).where(model.user_id == uid)


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
    """A real Postgres provider; skips if unreachable or the full schema is not applied."""
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — integration test skipped")
    prov = PostgresConnectionProvider.from_settings(settings)
    try:
        async with prov.session() as db:
            await db.execute(select(UserMemory).limit(1))
    except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
        await prov.aclose()
        pytest.skip("schema (migrations) not applied — run `alembic upgrade head`")
    try:
        yield prov
    finally:
        await prov.aclose()


async def _seed_full_user(provider: PostgresConnectionProvider) -> tuple[str, str]:
    """Insert a user with one row in every user-owned table. Returns (user_id, session_id)."""
    async with provider.session() as db:
        user = User(
            provider="google",
            sub=f"sub-{uuid4().hex[:12]}",
            email=f"{uuid4().hex[:8]}@example.com",
            display_name="Erase Me",
        )
        db.add(user)
        await db.flush()
        uid = user.id

        db.add(Profile(user_id=uid, data={"skills": ["Python"]}))
        db.add(Preference(user_id=uid, data={"tone": "concise"}))

        session_id = uuid4().hex
        db.add(Session(id=session_id, user_id=uid))
        conversation = Conversation(session_id=session_id, user_id=uid, title="Chat")
        db.add(conversation)
        await db.flush()

        message = Message(
            conversation_id=conversation.id,
            message_id=uuid4().hex,
            role="assistant",
            content="Hello",
        )
        db.add(message)
        await db.flush()
        db.add(
            MessageFeedback(
                message_id=message.message_id, user_id=uid, session_id=session_id, rating="up"
            )
        )
        db.add(
            Feedback(
                user_id=uid,
                session_id=session_id,
                contact="reach@example.com",
                content="Great tool",
            )
        )

        kb_doc = KbDocument(title="My CV", source_type="user_cv", user_id=uid, content="cv")
        db.add(kb_doc)
        await db.flush()
        db.add(
            KbChunk(kb_document_id=kb_doc.id, chunk_index=0, content="cv chunk", embedding=_EMBED)
        )
        db.add(
            UserMemory(
                user_id=uid,
                text="Prefers Python",
                embedding=_EMBED,
                memory_type="preference",
            )
        )

        db.add(Pdp(user_id=uid, career_goal="Staff engineer", target_date=date(2027, 1, 1)))
        goal = Goal(user_id=uid, title="Grow", status="active", source="user")
        db.add(goal)
        await db.flush()
        milestone = Milestone(goal_id=goal.id, title="M1", status="pending", source="user")
        db.add(milestone)
        await db.flush()
        db.add(
            DashboardTask(
                goal_id=goal.id, milestone_id=milestone.id, title="T1", status="todo", source="user"
            )
        )
        db.add(ProgressEntry(user_id=uid, goal_id=goal.id, note="did it", source="user"))

        await db.commit()
        return str(uid), session_id


async def _seed_shared_kb(provider: PostgresConnectionProvider) -> uuid.UUID:
    """Insert a shared (``user_id IS NULL``) KB document + chunk. Returns its id."""
    async with provider.session() as db:
        doc = KbDocument(title="Shared guide", source_type="curated", user_id=None)
        db.add(doc)
        await db.flush()
        db.add(KbChunk(kb_document_id=doc.id, chunk_index=0, content="shared", embedding=_EMBED))
        await db.commit()
        return doc.id


async def _delete_user(provider: PostgresConnectionProvider, user_id: str) -> None:
    async with provider.session() as db:
        existing = await db.get(User, uuid.UUID(user_id))
        if existing is not None:
            await db.delete(existing)
            await db.commit()


async def _delete_doc(provider: PostgresConnectionProvider, doc_id: uuid.UUID) -> None:
    async with provider.session() as db:
        existing = await db.get(KbDocument, doc_id)
        if existing is not None:
            await db.delete(existing)
            await db.commit()


async def test_export_is_scoped_and_excludes_embeddings(
    provider: PostgresConnectionProvider,
) -> None:
    repo = PostgresAccountRepository(provider)
    user_id, _ = await _seed_full_user(provider)
    other_id, _ = await _seed_full_user(provider)
    shared_doc_id = await _seed_shared_kb(provider)
    try:
        export = await repo.export(user_id)

        # Every section is populated for the owner.
        assert export.user is not None and export.user["id"] == user_id
        assert export.profile is not None and export.profile["data"] == {"skills": ["Python"]}
        assert export.preferences is not None
        assert len(export.conversations) == 1
        assert len(export.messages) == 1
        assert len(export.message_feedback) == 1
        assert len(export.feedback) == 1
        assert len(export.kb_documents) == 1
        assert len(export.kb_chunks) == 1
        assert len(export.user_memories) == 1
        assert len(export.pdps) == 1
        assert len(export.goals) == 1
        assert len(export.milestones) == 1
        assert len(export.tasks) == 1
        assert len(export.progress_entries) == 1

        # Raw embeddings are excluded from the exported rows.
        assert "embedding" not in export.kb_chunks[0]
        assert "embedding" not in export.user_memories[0]

        # Strictly scoped: no other user's rows and no shared KB doc leaked in.
        assert export.user["id"] != other_id
        exported_doc_ids = {row["id"] for row in export.kb_documents}
        assert str(shared_doc_id) not in exported_doc_ids

        # The user gets their own feedback (incl. contact) back in the portability export.
        assert export.feedback[0]["contact"] == "reach@example.com"

        # An unknown other user's export shares nothing with this user's document.
        assert user_id not in {row["id"] for row in (await repo.export(other_id)).kb_documents}
    finally:
        await _delete_user(provider, user_id)
        await _delete_user(provider, other_id)
        await _delete_doc(provider, shared_doc_id)


async def test_delete_user_cascades_every_store(
    provider: PostgresConnectionProvider,
) -> None:
    repo = PostgresAccountRepository(provider)
    user_id, _ = await _seed_full_user(provider)
    other_id, _ = await _seed_full_user(provider)
    shared_doc_id = await _seed_shared_kb(provider)
    try:
        await repo.delete_user(user_id)

        uid = uuid.UUID(user_id)
        async with provider.session() as db:

            async def _count(statement: Any) -> int:
                return (await db.execute(statement)).scalar_one()

            # The whole footprint is gone via cascade — every user-owned table seeded by
            # ``_seed_full_user`` must have zero surviving rows (no orphan rows anywhere).
            assert await db.get(User, uid) is None
            # Direct user-owned tables.
            assert await _count(_owned(Profile, uid)) == 0
            assert await _count(_owned(Preference, uid)) == 0
            assert await _count(_owned(Session, uid)) == 0
            assert await _count(_owned(Conversation, uid)) == 0
            assert await _count(_owned(MessageFeedback, uid)) == 0
            assert await _count(_owned(UserMemory, uid)) == 0
            assert await _count(_owned(KbDocument, uid)) == 0
            assert await _count(_owned(Pdp, uid)) == 0
            assert await _count(_owned(Goal, uid)) == 0
            assert await _count(_owned(ProgressEntry, uid)) == 0
            # Grandchildren (no direct user_id — reached via their parent's FK).
            assert (
                await _count(
                    select(func.count())
                    .select_from(Message)
                    .join(Conversation, Message.conversation_id == Conversation.id)
                    .where(Conversation.user_id == uid)
                )
                == 0
            )
            assert (
                await _count(
                    select(func.count())
                    .select_from(KbChunk)
                    .join(KbDocument, KbChunk.kb_document_id == KbDocument.id)
                    .where(KbDocument.user_id == uid)
                )
                == 0
            )
            assert (
                await _count(
                    select(func.count())
                    .select_from(Milestone)
                    .join(Goal, Milestone.goal_id == Goal.id)
                    .where(Goal.user_id == uid)
                )
                == 0
            )
            assert (
                await _count(
                    select(func.count())
                    .select_from(DashboardTask)
                    .join(Goal, DashboardTask.goal_id == Goal.id)
                    .where(Goal.user_id == uid)
                )
                == 0
            )

            # The other user and the shared KB document are untouched.
            assert await db.get(User, uuid.UUID(other_id)) is not None
            assert await db.get(KbDocument, shared_doc_id) is not None

        # Deleting again is idempotent (no error, no extra effect).
        await repo.delete_user(user_id)
        async with provider.session() as db:
            assert await db.get(User, uuid.UUID(other_id)) is not None
    finally:
        await _delete_user(provider, user_id)
        await _delete_user(provider, other_id)
        await _delete_doc(provider, shared_doc_id)


async def test_delete_user_scrubs_feedback_contact(
    provider: PostgresConnectionProvider,
) -> None:
    repo = PostgresAccountRepository(provider)
    async with provider.session() as db:
        user = User(
            provider="google",
            sub=f"sub-{uuid4().hex[:12]}",
            email=f"{uuid4().hex[:8]}@example.com",
            display_name="Scrub Me",
        )
        db.add(user)
        await db.flush()
        uid = user.id
        feedback = Feedback(user_id=uid, contact="reach@example.com", content="Loved it")
        db.add(feedback)
        await db.flush()
        feedback_id = feedback.id
        await db.commit()
    try:
        await repo.delete_user(str(uid))
        async with provider.session() as db:
            row = await db.get(Feedback, feedback_id)
            # The feedback row survives the erase (SET NULL — product feedback outlives the
            # account, §4), but it is now truly anonymous: user_id detached and the contact
            # PII scrubbed. The free-text content is retained for analytics value.
            assert row is not None
            assert row.user_id is None
            assert row.contact is None
            assert row.content == "Loved it"
    finally:
        async with provider.session() as db:
            row = await db.get(Feedback, feedback_id)
            if row is not None:
                await db.delete(row)
                await db.commit()


async def test_delete_and_export_tolerate_malformed_id(
    provider: PostgresConnectionProvider,
) -> None:
    repo = PostgresAccountRepository(provider)
    # A non-UUID id is a fail-safe no-op / empty export, never a 500.
    await repo.delete_user("not-a-uuid")
    from app.schemas.account import AccountExport

    assert await repo.export("not-a-uuid") == AccountExport()
