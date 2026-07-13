"""Integration checks for the P6-02 market-intelligence schema against **real Postgres**.

Proves the ``role_profiles`` + ``job_postings`` table group created by migration ``0007``
is usable (design §5.6 "role requirements, not a job board"): JSONB round-trips, the
``job_postings`` ``(source, external_id)`` dedup key is still unique after the rename, the
new ``target_role`` / ``expires_at`` evidence columns work, ``match_score`` is gone, and
``role_profiles.canonical_role`` is unique (one profile per role, reused across users).
Both tables are **global / non-personal** — neither carries a ``user_id`` (§5.6 / §7.6).

Requires the docker-compose Postgres (``JSONB``/``UUID`` cannot be represented in SQLite).
The suite is **skipped automatically** when no Postgres is reachable or the ``0007`` schema
is not applied, and runs inside a single transaction rolled back at the end.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.repositories.models import JobPosting, RoleProfile


async def _postgres_reachable() -> bool:
    """True if the configured Postgres accepts a connection (else the suite skips)."""
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect():
            return True
    except Exception:  # noqa: BLE001 - any connect failure → skip, never error the suite
        return False
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A session whose outer transaction is rolled back, leaving the DB untouched."""
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — integration test skipped")

    engine = create_async_engine(settings.DATABASE_URL)
    conn = await engine.connect()
    trans = await conn.begin()
    db = AsyncSession(bind=conn, expire_on_commit=False)
    try:
        try:
            await db.execute(select(JobPosting).limit(1))
            await db.execute(select(RoleProfile).limit(1))
        except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
            pytest.skip("market schema (migration 0007) not applied — run `alembic upgrade head`")
        yield db
    finally:
        await db.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()


def _make_posting(**overrides: object) -> JobPosting:
    defaults: dict[str, object] = {
        "source": "serpapi",
        "external_id": f"ext-{uuid4().hex[:8]}",
        "target_role": "AI Solution Architect",
        "title": "AI Solution Architect",
        "expires_at": datetime.now(UTC) + timedelta(days=1),
    }
    defaults.update(overrides)
    return JobPosting(**defaults)


async def test_match_score_column_dropped() -> None:
    """P6 drops per-posting match scoring (§5.6) — the column/attribute is gone."""
    assert not hasattr(JobPosting, "match_score")
    assert "match_score" not in inspect(JobPosting).columns


async def test_tables_are_global_no_user_id() -> None:
    """Both market tables are non-personal (§5.6/§7.6) — no ``user_id`` column."""
    assert "user_id" not in inspect(JobPosting).columns
    assert "user_id" not in inspect(RoleProfile).columns


async def test_job_posting_round_trip_and_jsonb(session: AsyncSession) -> None:
    """Insert a posting, read it back — JSONB ``raw`` + evidence columns usable."""
    expires = datetime.now(UTC) + timedelta(days=2)
    posting = _make_posting(
        source_url="https://example.com/jobs/123",
        company="Acme",
        location="Remote",
        description="Design LLM systems.",
        raw={"tags": ["rag", "vector-db"]},
        expires_at=expires,
    )
    session.add(posting)
    await session.flush()
    posting_id = posting.id
    session.expire_all()

    fetched = (
        await session.execute(select(JobPosting).where(JobPosting.id == posting_id))
    ).scalar_one()
    assert fetched.raw == {"tags": ["rag", "vector-db"]}
    assert fetched.target_role == "AI Solution Architect"
    assert fetched.expires_at is not None


async def test_job_posting_dedup_key_unique(session: AsyncSession) -> None:
    """The renamed ``(source, external_id)`` dedup key rejects a duplicate posting."""
    ext = f"ext-{uuid4().hex[:8]}"
    session.add(_make_posting(source="linkedin", external_id=ext))
    await session.flush()
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(_make_posting(source="linkedin", external_id=ext))
            await session.flush()


async def test_role_profile_round_trip_and_defaults(session: AsyncSession) -> None:
    """A role profile stores JSONB requirements/sources; server defaults apply."""
    profile = RoleProfile(
        canonical_role=f"AI Solution Architect {uuid4().hex[:6]}",
        taxonomy_id="esco:2511",
        requirements={"RAG": {"frequency": 0.78, "weight": 1.0, "evidence": ["https://x/1"]}},
        sources=["https://x/1", "esco"],
        evidence_count=3,
    )
    session.add(profile)
    await session.flush()
    profile_id = profile.id
    session.expire_all()

    fetched = (
        await session.execute(select(RoleProfile).where(RoleProfile.id == profile_id))
    ).scalar_one()
    assert fetched.requirements["RAG"]["frequency"] == 0.78
    assert fetched.sources == ["https://x/1", "esco"]
    assert fetched.evidence_count == 3
    assert fetched.refreshed_at is None


async def test_role_profile_server_side_defaults(session: AsyncSession) -> None:
    """requirements={} / sources=[] / evidence_count=0 apply when omitted."""
    profile = RoleProfile(canonical_role=f"Data Engineer {uuid4().hex[:6]}")
    session.add(profile)
    await session.flush()
    profile_id = profile.id
    session.expire_all()

    fetched = (
        await session.execute(select(RoleProfile).where(RoleProfile.id == profile_id))
    ).scalar_one()
    assert fetched.requirements == {}
    assert fetched.sources == []
    assert fetched.evidence_count == 0


async def test_role_profile_canonical_role_unique(session: AsyncSession) -> None:
    """One profile per canonical role — a duplicate ``canonical_role`` is rejected."""
    role = f"Platform Engineer {uuid4().hex[:6]}"
    session.add(RoleProfile(canonical_role=role))
    await session.flush()
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(RoleProfile(canonical_role=role))
            await session.flush()
