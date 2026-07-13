"""Market-intelligence ORM models (design §5.6 — role requirements, not a job board).

The market-intel table group of the v2 schema (P6). Every class subclasses the shared
:class:`~app.repositories.postgres.Base` so it lands on the one ``metadata`` Alembic
autogenerates from and the repository layer queries through.

Two tables live here — the *durable artifact* and its *raw evidence*:

* :class:`RoleProfile` — **the durable market artifact (§5.6).** One row per canonical role
  (e.g. *AI Solution Architect*): the taxonomy-matched title, an aggregated
  ``requirements JSONB`` (skill → frequency / weight / evidence refs), the contributing
  ``sources``, an ``evidence_count`` and a ``refreshed_at`` TTL marker. **Global — not
  user-scoped:** the market's requirements for a role are the same for everyone, so
  extraction is paid **once** and amortized across all users, and the data is
  **non-personal aggregate** (never cascaded on a user-delete).

* :class:`JobPosting` *(the renamed P2-05 ``jobs`` table)* — **raw evidence only, not
  inventory (§5.6).** Crawled/fetched postings used solely as *input* to
  :class:`RoleProfile` aggregation: TTL-cached (``expires_at``), deduped on
  ``(source, external_id)``, mined for a specific ``target_role``, and **stripped of
  third-party PII at ingest** (recruiter names / emails / phone numbers — those people
  never consented; §7.6). Never surfaced to users as a browsable list, never user-scoped.

Design constraints baked into the schema here:

* **Per-posting match scoring is dropped (§5.6, P6).** The P2-05 ``jobs.match_score``
  column is **removed**: *"match scoring" now means ``user profile ↔ role_profile`` — the
  skills gap itself — and is computed on demand, not stored on a posting.* There is no
  ``GET/POST /api/jobs`` surface either; postings are internal evidence.
* **Dedup key = ``(source, external_id)``** (unchanged from P2-05). ``source`` names the
  origin (``serpapi``, ``crawl`` …) and ``external_id`` is that provider's stable listing
  id (or a synthetic hash of the canonical URL for crawled profiles). ``source_url`` is
  nullable, non-unique reference/display metadata (URLs redirect / carry tracking params).
* **``raw JSONB``** keeps the original source payload verbatim for re-parsing without
  re-crawling (§4).
* **No ``user_id`` / no cascade on either table.** Both are shared, global, non-personal
  (§5.6); a GDPR user-delete (§7.6) never touches them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.repositories.models._mixins import CreatedAtMixin
from app.repositories.postgres import Base


class RoleProfile(CreatedAtMixin, Base):
    """The durable, global market artifact for one canonical role (§5.6).

    Aggregated **once** from an occupation taxonomy (ESCO / O*NET baseline) plus a recency
    delta of :class:`JobPosting` evidence, then reused by every user targeting that role.
    **Non-personal, never user-scoped** — a user-delete (§7.6) does not touch it.
    """

    __tablename__ = "role_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # The normalized/taxonomy-matched role title — one profile per canonical role
    # ("extraction happens once per role, reused across users", §5.6). Unique.
    canonical_role: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    # ESCO / O*NET occupation id from P6-01's taxonomy seed, when the role matched one.
    # Nullable — a user-stated role may have no clean taxonomy match.
    taxonomy_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Aggregated requirements: {"<skill>": {"frequency": <0-1>, "weight": <float>,
    # "evidence": [<job_posting id / source url>, ...]}} — every requirement is cited (§5.6).
    requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Source identifiers / urls that contributed to this profile (taxonomy + postings).
    sources: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    # How many evidence items (postings + taxonomy entries) backed the aggregation.
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # TTL staleness marker (§5.6): a periodic Celery refresh re-mines stale roles. Nullable
    # until the first aggregation runs.
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class JobPosting(CreatedAtMixin, Base):
    """A raw job posting — evidence for :class:`RoleProfile` aggregation only (§5.6).

    Deduplicated on ``(source, external_id)``, TTL-cached (``expires_at``), and mined for a
    specific ``target_role``. **Third-party PII (recruiter name/email/phone) is stripped at
    ingest** (§7.6, enforced in the P6-04 ingestion code — this schema supports it). Never
    surfaced to users as a browsable list, never user-scoped, no per-posting match score.
    """

    __tablename__ = "job_postings"
    __table_args__ = (
        # Provider-native dedup key: one row per (origin, provider listing id).
        UniqueConstraint("source", "external_id", name="uq_job_postings_source_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # Origin of the listing: an aggregator/provider name or "crawl".
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    # The provider's stable listing id (or a synthetic hash of the canonical URL for
    # crawled profiles). Together with ``source`` this is the dedup key.
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # The canonical role this posting was mined as evidence for (§5.6). Indexed — the
    # aggregation reads all postings for a target role.
    target_role: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    # Canonical listing URL — reference/display/re-crawl only, NOT the dedup key (URLs
    # redirect and carry tracking params). Indexed for lookups; non-unique.
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str | None] = mapped_column(String(512), nullable=True)
    location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Original crawled/source payload, kept verbatim for re-parsing without re-crawling.
    # (Already PII-stripped at ingest — §7.6.)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # TTL cache expiry (§5.6): the ingestion/refresh layer treats a posting past this as
    # stale. Indexed so a periodic sweep can find expired rows efficiently.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # When the source was last fetched/crawled (distinct from row ``created_at``).
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
