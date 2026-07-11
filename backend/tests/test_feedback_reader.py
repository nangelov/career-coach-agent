"""Unit tests for the feedback-read port double (P3-05).

Covers the process-local :class:`~app.services.feedback.InMemoryFeedbackReader` contract the
admin feedback endpoint depends on: entries come back newest-first and honour the ``limit``,
mirroring the Postgres adapter's ordering.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.schemas.feedback import FeedbackEntry
from app.services.feedback import InMemoryFeedbackReader


def _entry(entry_id: str, *, minutes_ago: int) -> FeedbackEntry:
    return FeedbackEntry(
        id=entry_id,
        content=f"content {entry_id}",
        contact=None,
        user_id=None,
        session_id=None,
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


async def test_empty_reader_returns_empty_list() -> None:
    reader = InMemoryFeedbackReader()
    assert await reader.list_feedback(limit=10) == []


async def test_orders_newest_first() -> None:
    reader = InMemoryFeedbackReader([_entry("old", minutes_ago=30), _entry("new", minutes_ago=1)])
    result = await reader.list_feedback(limit=10)
    assert [e.id for e in result] == ["new", "old"]


async def test_respects_limit() -> None:
    reader = InMemoryFeedbackReader(
        [
            _entry("a", minutes_ago=3),
            _entry("b", minutes_ago=2),
            _entry("c", minutes_ago=1),
        ]
    )
    result = await reader.list_feedback(limit=2)
    # Two newest only.
    assert [e.id for e in result] == ["c", "b"]
