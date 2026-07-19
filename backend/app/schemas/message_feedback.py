"""Per-message 👍/👎 feedback contracts (§5.5 / §7 — teachable-memory learning loop).

The request/response shape for ``POST /api/messages/{message_id}/feedback`` (P9-01): a user
rates a single assistant turn thumbs-up/down with an optional free-text reason. This is the
**capture** surface only — the LangMem learn step (P9-03) and the frontend widget (P9-09) are
separate tasks that *consume* the ``message_feedback`` rows this endpoint writes.

Kept in its own module (not ``schemas/feedback.py``, which is the *product*-feedback surface)
so the two distinct feedback concepts — per-message reaction vs. free-text product feedback —
each have one home.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

#: The thumbs rating carried in the request/response and persisted in ``message_feedback.rating``
#: — kept in lockstep with the ``ck_message_feedback_rating`` check constraint (``up`` / ``down``).
MessageRating = Literal["up", "down"]

#: Upper bound on the free-text reason. Generous enough for a sentence or two of "why", short
#: enough to keep the column a plain, unindexed note (§7.6: no special handling at capture time).
MAX_REASON_LENGTH = 2000


class MessageFeedbackRequest(BaseModel):
    """``POST /api/messages/{message_id}/feedback`` body — a thumbs rating + optional reason.

    ``rating`` is required (👍/👎 is the whole point); ``reason`` is optional free text the
    frontend collects on a thumbs-down (or leaves empty). The ``message_id`` is a path param,
    not a body field, so a caller cannot point the body at a different message than the URL.
    """

    rating: MessageRating = Field(..., description="Thumbs rating for the assistant message.")
    reason: str | None = Field(
        default=None,
        max_length=MAX_REASON_LENGTH,
        description="Optional free-text reason (e.g. why the answer was unhelpful).",
    )


class MessageFeedbackResponse(BaseModel):
    """The stored per-message feedback returned after a successful capture (or read).

    Echoes back what was persisted so the client can render the confirmed state (and, on a
    resubmission, see the rating/reason it just changed to). Owner ids are intentionally not
    surfaced — the caller already *is* the owner, and this keeps another user's identity off
    the wire.
    """

    message_id: str = Field(..., description="The rated message's stable app id (§5.5).")
    rating: MessageRating = Field(..., description="The stored thumbs rating.")
    reason: str | None = Field(default=None, description="The stored free-text reason, if any.")
    created_at: datetime = Field(..., description="When the feedback was last submitted (UTC).")
