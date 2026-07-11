"""Free-text product feedback contracts (§4 ``feedback`` / §9 API table).

The read side of the v2 product-feedback surface. v1 dumped per-day JSON files through
``GET /get-feedback?key=<HF_TOKEN>`` (authenticated by matching the LLM API token in the
query string); v2 stores feedback in Postgres (``feedback`` table) and exposes it through an
**admin-only** ``GET /api/feedback`` — this module is the response contract that endpoint
returns.

Only the read model lives here for now; the ``POST /api/feedback`` submit body is a separate
task. Kept in its own module (not ``schemas/chat.py``) so the feedback surface has one home.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FeedbackEntry(BaseModel):
    """One free-text product-feedback record (a row of the ``feedback`` table).

    ``user_id`` / ``session_id`` are optional because the table's FKs are ``ON DELETE SET
    NULL`` (§4): product feedback outlives the account that submitted it, so an entry may be
    detached from any user/session after a GDPR delete. ``contact`` mirrors v1's optional
    contact field.
    """

    id: str = Field(..., description="Feedback row id (UUID as string).")
    content: str = Field(..., description="The free-text feedback body.")
    contact: str | None = Field(default=None, description="Optional contact left by the author.")
    user_id: str | None = Field(default=None, description="Submitting users.id, or None.")
    session_id: str | None = Field(default=None, description="Submitting session id, or None.")
    created_at: datetime = Field(..., description="When the feedback was submitted (UTC).")


class FeedbackListResponse(BaseModel):
    """``GET /api/feedback`` response — the admin feedback listing.

    A thin wrapper (rather than a bare array) so the payload can grow paging metadata later
    without a breaking response-shape change. ``count`` is the number of returned items.
    """

    items: list[FeedbackEntry]
    count: int = Field(..., description="Number of entries returned.")
