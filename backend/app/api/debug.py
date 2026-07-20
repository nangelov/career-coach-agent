"""Debug / operational-verification endpoints — admin only (§7.7, S15).

A single **admin-gated** endpoint to deliberately raise an unhandled exception so an operator
can confirm Sentry error delivery end-to-end against a real project/DSN (P11-05-verify uses it).

It is gated by :func:`~app.security.dependencies.require_admin` — never anonymous, never a
guest — because a public "throw an error" route is a trivial log/alert-spam vector. When Sentry
is not configured (``SENTRY_DSN`` unset) the route simply surfaces the error as a normal ``500``;
when it is configured, the FastAPI Sentry integration captures the unhandled exception and it
appears (PII-scrubbed) in the Sentry project. This is verification tooling only — it is *not*
part of any product flow (§7.7: this is a low-noise error channel, not on-call tooling).
"""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends

from app.schemas.auth import CurrentUser
from app.security.dependencies import require_admin

router = APIRouter(prefix="/api/_debug", tags=["debug"])


class SentryTestError(RuntimeError):
    """Deliberate, benign error raised by the Sentry-test endpoint to verify delivery."""


@router.get("/sentry-test", response_model=None)
async def sentry_test(_admin: CurrentUser = Depends(require_admin)) -> NoReturn:
    """Raise a deliberate unhandled exception to verify Sentry delivery — **admin only**.

    Requires an authenticated session whose ``users`` row is flagged ``is_admin`` (a guest or
    ordinary user is a ``403``, an unauthenticated caller a ``401``). Raises
    :class:`SentryTestError`, which propagates as an unhandled ``500`` — captured (PII-scrubbed)
    by the Sentry FastAPI integration when ``SENTRY_DSN`` is configured, otherwise just a plain
    ``500``. Used by the operator / P11-05-verify to confirm the alert pipeline once a real DSN
    is set; it exposes nothing and is not part of any product flow.
    """
    raise SentryTestError(
        "Deliberate Sentry test error via GET /api/_debug/sentry-test (admin-triggered)."
    )
