"""Job-listing ORM models (design §4 — Postgres relational + JSONB).

Part of the third real table group of the v2 schema (P2-05, *structured records*).
Every class subclasses the shared :class:`~app.repositories.postgres.Base` so it lands on
the one ``metadata`` Alembic autogenerates from and the repository layer queries through.

Design constraints baked into the schema here:

* **Dedup key = ``(source, external_id)`` (§4: "dedup, cache, match scores").** A job is
  identified by its *provider-native* pair: ``source`` names the origin (``serpapi``,
  ``linkedin``, ``crawl`` …) and ``external_id`` is that provider's stable listing id. This
  is preferred over ``source_url`` as the dedup key because listing URLs redirect, carry
  tracking params, and differ across aggregators for the same role — a provider's own id is
  the stable natural key. Crawled role profiles that have no provider id still get a
  synthetic ``(source='crawl', external_id=<stable hash of the canonical URL>)`` from the
  ingestion layer, so every row has a dedup key. ``source_url`` is kept as nullable,
  non-unique reference metadata for re-crawl/display.
* **``raw JSONB`` (§4).** The original crawled/source payload is retained verbatim so a job
  can be re-parsed (better extraction, new fields) without re-crawling the source.
* **``match_score`` is a *global* placeholder, not the per-user score (§4).** A real
  job↔profile match is inherently **per-user** (it compares the listing to *a* user's
  profile), so it does not belong on a globally-shared ``jobs`` row. Per-user match scoring
  is deferred to a later feature via a ``user_job_matches`` join table (``user_id`` +
  ``job_id`` + ``score``); this nullable column is the documented schema-only simplification
  (it may hold an optional source-provided global relevance score in the meantime, or stay
  NULL). See the P2-05 ``engineer.md`` "Key decisions".
* **No ``user_id`` / no cascade.** ``jobs`` is a shared, global cache of listings owned by no
  single user (unlike the private CV docs in P2-04), so a GDPR user-delete does not touch it;
  the future per-user ``user_job_matches`` rows would carry the cascading ``user_id`` FK.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    Float,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.repositories.models._mixins import CreatedAtMixin
from app.repositories.postgres import Base


class Job(CreatedAtMixin, Base):
    """A normalized job listing / crawled role profile (§4).

    Deduplicated on ``(source, external_id)`` (see the module docstring). The raw source
    payload is kept in :attr:`raw` for re-processing without re-crawling.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        # Provider-native dedup key: one row per (origin, provider listing id).
        UniqueConstraint("source", "external_id", name="uq_jobs_source_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # Origin of the listing: an aggregator/provider name or "crawl".
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    # The provider's stable listing id (or a synthetic hash of the canonical URL for
    # crawled profiles). Together with ``source`` this is the dedup key.
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Canonical listing URL — reference/display/re-crawl only, NOT the dedup key (URLs
    # redirect and carry tracking params). Indexed for lookups; non-unique.
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str | None] = mapped_column(String(512), nullable=True)
    location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Original crawled/source payload, kept verbatim for re-parsing without re-crawling.
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Global relevance placeholder only — true per-user matching is deferred to a future
    # ``user_job_matches`` join table (see module docstring). Nullable.
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # When the source was last fetched/crawled (distinct from row ``created_at``).
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
