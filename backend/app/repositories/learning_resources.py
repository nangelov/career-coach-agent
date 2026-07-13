"""Repository helper for the shared learning-resource corpus (design §5.7, §8 layering).

The learning-resource corpus lives in the existing P2-04 ``kb_documents`` / ``kb_chunks``
schema (shared, ``user_id IS NULL``, ``source_type='curated'``) — no dedicated table — so the
only bespoke datastore access it needs is the **skill-keyed lookup** the P7 PDP will use:
*"which resources cover skill X?"*. That query lives here (services/agents never touch the
driver — §8), keyed on the normalized ``skill_keys`` list the ingestion pipeline stamps into
each document's ``meta`` JSONB.

The ingestion pipeline's *writes* reuse the existing shared write path
(:func:`~app.repositories.vector_search.add_kb_chunk` + an inline idempotent document upsert,
the same precedent as :mod:`app.ingestion.taxonomy_seed`), so there is no second write helper
here — only the read the downstream consumer needs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.repositories.kb_kinds import LEARNING_RESOURCE_KIND
from app.repositories.models.knowledge import KbDocument

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: Re-exported from :mod:`app.repositories.kb_kinds` (the single source of truth for the shared
#: corpus' ``meta["kind"]`` markers) so existing importers of this symbol keep working while the
#: literal is defined exactly once.
__all__ = ["LEARNING_RESOURCE_KIND", "list_resources_for_skill"]


async def list_resources_for_skill(session: AsyncSession, skill: str) -> list[KbDocument]:
    """Return the shared learning-resource documents that cover ``skill`` (design §5.7).

    Case-insensitive: matches against the normalized ``meta.skill_keys`` list the ingestion
    pipeline stamps (each skill lower-cased), via a single JSONB containment (``@>``) predicate
    — no new index/migration required. Only shared (``user_id IS NULL``) curated resources are
    considered, so every user and guest sees the same corpus (§5.7 "global + amortized").
    Returns an empty list for a blank skill or no match.
    """
    key = skill.strip().lower()
    if not key:
        return []
    stmt = select(KbDocument).where(
        KbDocument.user_id.is_(None),
        KbDocument.source_type == "curated",
        KbDocument.meta.contains({"kind": LEARNING_RESOURCE_KIND, "skill_keys": [key]}),
    )
    rows = await session.execute(stmt)
    return list(rows.scalars().all())
