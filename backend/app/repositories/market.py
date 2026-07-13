"""Repository helpers for the market-intelligence tables (design §5.6, §8 layering).

All datastore access for the P6-02 ``role_profiles`` / ``job_postings`` group lives here —
the market agent (request-path read) and the mining Celery pipeline (write) call these
instead of hand-rolling SQL, keeping the agent/service layers off the driver (§8). Following
the :mod:`app.repositories.vector_search` convention, the write helpers ``flush`` (so the PK
is populated) but never ``commit`` — the caller owns the transaction boundary.

Two read paths (request-path MARKET_INTEL worker) and two upserts (mining pipeline):

* :func:`shared_kb_document_ids` / :func:`document_titles` — resolve the **shared** KB
  (``user_id IS NULL``) the market worker searches over, and the parent-doc titles for its
  citations. The market corpus (taxonomy + role-profile summaries) is global, so — unlike the
  RAG worker — there is no per-user scoping here.
* :func:`get_role_profile` / :func:`list_role_profiles` — read the cached
  :class:`~app.repositories.models.market.RoleProfile` row(s) the worker surfaces (the
  structured requirements behind the grounded snippets).
* :func:`upsert_role_profile` — the mining aggregation's idempotent write, keyed on the
  unique ``canonical_role`` (one profile per role, reused across users — §5.6).
* :func:`upsert_job_posting` — the mining evidence write, deduped on ``(source, external_id)``
  (§5.6). Posting text is expected **already PII-stripped** by the caller (§7.6).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.repositories.models.knowledge import KbDocument
from app.repositories.models.market import JobPosting, RoleProfile

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "document_titles",
    "get_role_profile",
    "list_role_profiles",
    "shared_kb_document_ids",
    "upsert_job_posting",
    "upsert_role_profile",
]


async def shared_kb_document_ids(
    session: AsyncSession, *, source_types: Sequence[str] | None = None
) -> list[uuid.UUID]:
    """Resolve the shared KB document ids (``user_id IS NULL``) the market corpus lives in.

    Optionally restrict to specific ``source_types`` (e.g. only the ``curated`` taxonomy docs
    when resolving a role baseline). The shared corpus is global and non-personal (§5.6), so
    there is no per-user filtering — every user and guest sees the same market KB.
    """
    stmt = select(KbDocument.id).where(KbDocument.user_id.is_(None))
    if source_types is not None:
        stmt = stmt.where(KbDocument.source_type.in_(list(source_types)))
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


async def document_titles(session: AsyncSession, doc_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Look up parent-document titles for the retrieved chunks (one batched query)."""
    if not doc_ids:
        return {}
    rows = await session.execute(
        select(KbDocument.id, KbDocument.title).where(KbDocument.id.in_(doc_ids))
    )
    return {row.id: row.title for row in rows.all()}


async def get_role_profile(session: AsyncSession, canonical_role: str) -> RoleProfile | None:
    """Read the cached :class:`RoleProfile` for ``canonical_role`` (unique key), or ``None``."""
    return (
        await session.execute(
            select(RoleProfile).where(RoleProfile.canonical_role == canonical_role)
        )
    ).scalar_one_or_none()


async def list_role_profiles(
    session: AsyncSession, canonical_roles: Sequence[str]
) -> list[RoleProfile]:
    """Batch-read the cached :class:`RoleProfile` rows for ``canonical_roles`` (deduped)."""
    roles = list(dict.fromkeys(r for r in canonical_roles if r))
    if not roles:
        return []
    rows = await session.execute(select(RoleProfile).where(RoleProfile.canonical_role.in_(roles)))
    return list(rows.scalars().all())


async def upsert_role_profile(
    session: AsyncSession,
    *,
    canonical_role: str,
    taxonomy_id: str | None,
    requirements: dict[str, Any],
    sources: Sequence[Any],
    evidence_count: int,
    refreshed_at: datetime,
) -> RoleProfile:
    """Insert or update the global :class:`RoleProfile` for ``canonical_role`` (unique key).

    Idempotent by ``canonical_role`` (one profile per role, amortized across all users — §5.6):
    an existing row is updated in place, otherwise a fresh row is inserted. Does not commit —
    the caller owns the transaction (the mining pipeline's persist step).
    """
    profile = await get_role_profile(session, canonical_role)
    if profile is None:
        profile = RoleProfile(canonical_role=canonical_role)
        session.add(profile)
    profile.taxonomy_id = taxonomy_id
    profile.requirements = dict(requirements)
    profile.sources = list(sources)
    profile.evidence_count = evidence_count
    profile.refreshed_at = refreshed_at
    await session.flush()
    return profile


async def upsert_job_posting(
    session: AsyncSession,
    *,
    source: str,
    external_id: str,
    target_role: str,
    title: str,
    source_url: str | None,
    company: str | None,
    location: str | None,
    description: str | None,
    raw: dict[str, Any],
    expires_at: datetime,
    fetched_at: datetime,
) -> JobPosting:
    """Insert or update a :class:`JobPosting` deduped on ``(source, external_id)`` (§5.6).

    Raw evidence only — never browsable inventory. ``description`` / ``raw`` are expected
    **already PII-stripped** by the caller (recruiter name/email/phone — §7.6). Does not
    commit; the caller owns the transaction.
    """
    existing = (
        await session.execute(
            select(JobPosting).where(
                JobPosting.source == source,
                JobPosting.external_id == external_id,
            )
        )
    ).scalar_one_or_none()
    posting = existing or JobPosting(source=source, external_id=external_id)
    if existing is None:
        session.add(posting)
    posting.target_role = target_role
    posting.title = title
    posting.source_url = source_url
    posting.company = company
    posting.location = location
    posting.description = description
    posting.raw = dict(raw)
    posting.expires_at = expires_at
    posting.fetched_at = fetched_at
    await session.flush()
    return posting
