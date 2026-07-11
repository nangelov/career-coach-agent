"""Product-feedback read seam (Postgres-backed in :mod:`app.repositories.feedback_store`).

The admin feedback-read endpoint (``GET /api/feedback``, the P3-05 replacement for v1's
``GET /get-feedback?key=<HF_TOKEN>``) needs exactly one capability: list the stored
free-text product feedback, most-recent first. That single read gets a narrow port here,
following the interface-before-implementation idiom used across the codebase (``UserStore``,
``SessionStore``, …): this module defines the port plus a process-local implementation for
tests; the **Postgres-backed** adapter
(:class:`~app.repositories.feedback_store.PostgresFeedbackReader`) lives in the repository
layer.

Read-only by design — submitting feedback (``POST /api/feedback``) is a separate concern and
a separate task; keeping the read port minimal avoids speculative write methods (YAGNI).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.feedback import FeedbackEntry


class FeedbackReader(ABC):
    """List stored free-text product feedback (§4 ``feedback``), newest first.

    Implementations own storage (process-local here, Postgres in the repository layer);
    the admin endpoint depends only on this interface.
    """

    @abstractmethod
    async def list_feedback(self, *, limit: int) -> list[FeedbackEntry]:
        """Return up to ``limit`` feedback entries, ordered newest-first.

        ``limit`` is a positive upper bound the caller has already validated (the endpoint
        clamps it to a sane range). Returns an empty list when there is no feedback.
        """


class InMemoryFeedbackReader(FeedbackReader):
    """Process-local :class:`FeedbackReader` — test double only.

    Holds a list of :class:`FeedbackEntry` and returns the most recent ``limit`` by
    ``created_at`` (newest first), mirroring the Postgres adapter's ordering. Not for
    production.
    """

    def __init__(self, entries: list[FeedbackEntry] | None = None) -> None:
        self._entries = list(entries or [])

    async def list_feedback(self, *, limit: int) -> list[FeedbackEntry]:
        ordered = sorted(self._entries, key=lambda e: e.created_at, reverse=True)
        return ordered[: max(0, limit)]
