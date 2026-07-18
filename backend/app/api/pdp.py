"""PDP API — generate a styled PDF from the stored profile (P7-03, §5.2 / §9).

The thin router (Router → Service → Agent/Repository, §8) for ``POST /api/pdp``, the v2
replacement for v1's ``POST /pdp-generator``. It owns HTTP concerns only — auth gating,
rate-limit enforcement, and mapping the :class:`~app.services.pdp.PdpService` outcomes onto
status codes / the PDF response — and delegates the whole generation flow (load stored profile →
skills gap → generate → validate → render → persist) to the injected service.

**No file upload (task / §4).** Unlike v1's multipart ``/pdp-generator``, the request carries only
a :class:`~app.schemas.pdp.PdpRequest` (career goal + optional target date / context): the plan is
built from the caller's **stored** structured profile (P5), so regenerating a plan never requires
re-uploading a CV.

**Auth required, guests rejected (``403``).** A PDP needs a persisted profile, which only
logged-in users have (mirrors ``GET /api/roles/{role}/gap`` and ``PUT /api/profile``). A guest
(``user_id=None``) is a ``403`` before any work is done.

**Clear, non-5xx degradation (task acceptance).** A missing profile is a ``422`` ("upload a CV
first"), an unmined role still returns a best-effort PDF (stamped ``X-PDP-Status`` so the client
can tell), and a plan that cannot be made substantial after the bounded retry is a ``502`` — never
a raw ``500`` or a broken PDF.

Dependency wiring is lazy: the service is assembled by the composition root (:mod:`app.bootstrap`)
on first use and cached on ``app.state``. Tests override :func:`get_pdp_service` (and the
auth/rate-limit deps) to inject fakes so no real HF/Postgres/Redis wiring runs in unit tests.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.app_state import AppStateKeys
from app.bootstrap import build_pdp_service
from app.schemas.auth import CurrentUser
from app.schemas.pdp import PdpRequest
from app.security.dependencies import (
    get_rate_limit_service,
    rate_limit_exceeded_http,
    require_auth,
)
from app.services.pdp import (
    PdpGenerated,
    PdpGenerationFailed,
    PdpProfileMissing,
    PdpService,
)
from app.services.rate_limiting import RateLimitAction, RateLimitExceeded, RateLimitService

router = APIRouter(prefix="/api", tags=["pdp"])


def get_pdp_service(request: Request) -> PdpService:
    """FastAPI dependency: the app-scoped :class:`PdpService`, built once and cached.

    Delegates construction to the composition root (:func:`app.bootstrap.build_pdp_service`) and
    caches the singleton on ``app.state``. Tests override this dependency to inject a fake so the
    real HF/Postgres wiring never runs in unit tests.
    """
    service: PdpService | None = getattr(request.app.state, AppStateKeys.PDP_SERVICE, None)
    if service is None:
        service = build_pdp_service(request.app)
        setattr(request.app.state, AppStateKeys.PDP_SERVICE, service)
    return service


def _pdf_filename(career_goal: str) -> str:
    """Build v1's ``PDP_<slug>.pdf`` download name from the career goal (safe, bounded).

    Mirrors v1: strip non-word characters, collapse whitespace/dashes to a single dash. Bounded
    and falling back to a generic name so an all-symbol goal still yields a valid filename.
    """
    slug = re.sub(r"[^\w\s-]", "", career_goal).strip()
    slug = re.sub(r"[-\s]+", "-", slug)[:64].strip("-")
    return f"PDP_{slug}.pdf" if slug else "PDP.pdf"


@router.post("/pdp")
async def generate_pdp_endpoint(
    payload: PdpRequest,
    current_user: CurrentUser = Depends(require_auth),
    service: PdpService = Depends(get_pdp_service),
    rate_limiter: RateLimitService = Depends(get_rate_limit_service),
) -> Response:
    """Generate a Personal Development Plan PDF from the caller's stored profile (§5.2).

    Requires a logged-in user (guests → ``403``: a PDP needs a persisted profile). The message
    budget is charged first (reusing the same action as chat/roles), then the service runs the
    full flow. Outcomes map to: ``422`` (no stored profile — upload a CV first), ``502`` (the
    plan could not be made substantial after the bounded retry), or ``200`` with the styled PDF
    (``application/pdf``, a ``PDP_<goal>.pdf`` download name, and an ``X-PDP-Status`` header
    telling the client whether the target role was mined). Every returned PDF is gated by
    ``validate_pdp_content`` and backed by a persisted ``pdps`` row.
    """
    if current_user.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guests cannot generate a PDP. Sign in and upload a CV first.",
        )

    try:
        await rate_limiter.enforce(RateLimitAction.MESSAGE, current_user)
    except RateLimitExceeded as exc:
        raise rate_limit_exceeded_http(exc) from exc

    outcome = await service.generate(
        user_id=current_user.user_id,
        career_goal=payload.career_goal,
        target_date=payload.target_date,
        additional_context=payload.additional_context,
    )

    if isinstance(outcome, PdpProfileMissing):
        raise HTTPException(
            # 422 Unprocessable Content — literal to stay stable across Starlette's constant
            # rename (same posture as ``app/api/profile.py``'s 413).
            status_code=422,
            detail="No profile found. Please upload your CV first, then generate a plan.",
        )
    if isinstance(outcome, PdpGenerationFailed):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not generate a complete plan right now. Please try again in a moment.",
        )
    if not isinstance(outcome, PdpGenerated):  # pragma: no cover - exhaustive guard
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected PDP generation outcome.",
        )

    filename = _pdf_filename(payload.career_goal)
    return Response(
        content=outcome.pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-PDP-Status": outcome.status,
        },
    )
