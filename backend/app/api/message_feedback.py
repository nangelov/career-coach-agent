"""Message-feedback API — capture per-message 👍/👎 + reason (P9-01, §5.5 / §9).

The thin router (Router → Service → Repository, §8) for
``POST /api/messages/{message_id}/feedback``: it owns HTTP concerns only — auth gating, path/
body shaping, and mapping the store's outcome onto a status code — and delegates ownership
validation + persistence to the injected
:class:`~app.services.message_feedback.MessageFeedbackStore` port.

**Auth required; guests included (no new unauthenticated surface, §7).** Any authenticated
caller — logged-in *or* guest — may rate a message they own; the *identity* comes from the
verified token (``require_auth``), never from the request body, so a caller cannot claim
another user's ownership. Ownership itself is enforced in the store: a message that does not
exist *or* is not the caller's reads as a uniform ``404`` (never distinguishing the two, so
the endpoint cannot be used to probe another user's message ids — mirroring ``dashboard.py``).

Dependency wiring is lazy: the store is assembled by the composition root (:mod:`app.bootstrap`)
on first use and cached on ``app.state``. Tests override :func:`get_message_feedback_store`
(and the auth dependency) to inject fakes so no real Postgres wiring runs in unit tests.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.app_state import AppStateKeys
from app.bootstrap import build_message_feedback_store
from app.schemas.auth import CurrentUser
from app.schemas.message_feedback import MessageFeedbackRequest, MessageFeedbackResponse
from app.security.dependencies import require_auth
from app.services.message_feedback import MessageFeedbackStore

router = APIRouter(prefix="/api/messages", tags=["message-feedback"])


def get_message_feedback_store(request: Request) -> MessageFeedbackStore:
    """FastAPI dependency: the app-scoped :class:`MessageFeedbackStore`, built once and cached.

    Delegates construction to the composition root
    (:func:`app.bootstrap.build_message_feedback_store`) and caches the singleton on
    ``app.state``. Tests override this dependency to inject an in-memory store so the real
    Postgres wiring never runs in unit tests.
    """
    store: MessageFeedbackStore | None = getattr(
        request.app.state, AppStateKeys.MESSAGE_FEEDBACK_STORE, None
    )
    if store is None:
        store = build_message_feedback_store(request.app)
        setattr(request.app.state, AppStateKeys.MESSAGE_FEEDBACK_STORE, store)
    return store


@router.post("/{message_id}/feedback")
async def submit_message_feedback(
    message_id: str,
    payload: MessageFeedbackRequest,
    current_user: CurrentUser = Depends(require_auth),
    store: MessageFeedbackStore = Depends(get_message_feedback_store),
) -> MessageFeedbackResponse:
    """Capture the caller's 👍/👎 (+ optional reason) for one of their messages (§5.5).

    Idempotent: resubmitting for the same message flips the rating / edits the reason on the
    same row rather than duplicating it. A message that does not exist or is not the caller's
    is a uniform ``404`` (no ownership leak).
    """
    stored = await store.record(
        message_id=message_id,
        rating=payload.rating,
        reason=payload.reason,
        user_id=current_user.user_id,
        session_id=current_user.session_id,
    )
    if stored is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found.")
    return stored
