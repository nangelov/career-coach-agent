"""Feedback API — admin-only read of free-text product feedback (P3-05, §7/§9).

Replaces v1's ``GET /get-feedback?key=<HF_TOKEN>`` (which "authenticated" by matching the
LLM API token as a query-string ``key`` — a shared secret in the URL, not real access
control) with ``GET /api/feedback`` gated by :func:`~app.security.dependencies.require_admin`:
an authenticated session (P3-02 JWT) whose ``users`` row is flagged ``is_admin``.

This router is deliberately **thin** (Router → Service → Repository): it owns HTTP concerns
(the admin gate, query validation, response shape) and delegates the actual read to the
:class:`~app.services.feedback.FeedbackReader` port (Postgres-backed in the repository
layer). It imports no repository/driver types — only the port, schemas, and dependencies
(which delegate to the composition root) — so the endpoint is unit-testable with a fake
reader and no Postgres.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.app_state import AppStateKeys
from app.bootstrap import build_feedback_reader
from app.schemas.auth import CurrentUser
from app.schemas.feedback import FeedbackListResponse
from app.security.dependencies import require_admin
from app.services.feedback import FeedbackReader

router = APIRouter(prefix="/api", tags=["feedback"])

#: Default / maximum number of feedback entries returned per request. A single admin
#: listing does not need cursor paging yet (YAGNI); the cap just bounds the query.
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 1000


def get_feedback_reader(request: Request) -> FeedbackReader:
    """FastAPI dependency: the app-scoped :class:`FeedbackReader`, built once and cached.

    Delegates construction to the composition root
    (:func:`app.bootstrap.build_feedback_reader`) and caches the singleton on ``app.state``.
    Tests override this dependency to inject an in-memory reader so the real Postgres wiring
    never runs in unit tests.
    """
    reader: FeedbackReader | None = getattr(request.app.state, AppStateKeys.FEEDBACK_READER, None)
    if reader is None:
        reader = build_feedback_reader(request.app)
        setattr(request.app.state, AppStateKeys.FEEDBACK_READER, reader)
    return reader


@router.get("/feedback")
async def list_feedback(
    limit: int = Query(
        _DEFAULT_LIMIT,
        ge=1,
        le=_MAX_LIMIT,
        description="Maximum number of feedback entries to return (newest first).",
    ),
    _admin: CurrentUser = Depends(require_admin),
    reader: FeedbackReader = Depends(get_feedback_reader),
) -> FeedbackListResponse:
    """List free-text product feedback, newest first — **admin only** (§7/§9).

    Requires an authenticated session belonging to a user flagged ``is_admin``
    (:func:`~app.security.dependencies.require_admin`): an unauthenticated caller is a
    ``401`` and a non-admin (guest or ordinary user) is a ``403`` — no shared secret in the
    URL, unlike v1. Returns up to ``limit`` entries.
    """
    items = await reader.list_feedback(limit=limit)
    return FeedbackListResponse(items=items, count=len(items))
