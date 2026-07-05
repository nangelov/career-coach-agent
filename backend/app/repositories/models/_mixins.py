"""Shared ORM mixins for the model table groups (design §4/§8).

Small plumbing reused verbatim by every table group (``identity``, ``knowledge``,
``dashboard``, ``jobs``). Defined once here so a future change (e.g. timestamp
precision/timezone behavior) lands in a single place instead of half-landing across
four near-identical copies.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class CreatedAtMixin:
    """Adds a server-defaulted ``created_at`` timestamp (UTC, timezone-aware)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
