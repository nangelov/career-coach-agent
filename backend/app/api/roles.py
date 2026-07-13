"""Roles API — market requirement profiles + skills gap (P6-07, §5.6 / §9).

The thin router (Router → Service → Repository, §8) for the v2 market surface that *replaces*
v1's job-search (design §9: *"replaces `/api/jobs`; no listings"*). It owns HTTP concerns only —
auth gating, rate-limit enforcement, and mapping the :class:`~app.services.roles.RolesService`
outcomes onto status codes — and delegates all logic (cache-first read, canonicalization,
background mining) to the injected service. **No route triggers uncached crawling** (§5.6/§7.5):
a cold role always returns a mine-job handle, never a blocking crawl.

* ``GET /api/roles/{role}/requirements`` — **no login required** (§5.6: *"guests can query
  market requirements, no account needed"*). A valid guest/user token is used when present;
  otherwise the caller is anonymous and rate-limited by client IP. Cache hit → ``200`` with the
  ranked, cited requirements; cache miss (never mined) → ``202`` + a pollable ``task_id``.
* ``GET /api/roles/{role}/gap`` — **requires auth** and rejects guests (``403``): a skills gap
  needs a persisted profile, which only logged-in users have (mirrors ``PUT /api/profile``,
  P5-05). ``ok``/``profile_missing`` → ``200`` (self-describing ``status`` — never a 500 on a
  missing profile); ``role_profile_missing`` → ``202`` + a mine-job handle (same cold-start
  path as ``/requirements``).

The client polls the **existing** generic ``GET /api/jobs/status/{task_id}`` (P5-06) with any
returned ``task_id`` — this task builds no second status endpoint.

Dependency wiring is lazy: the service is assembled by the composition root
(:mod:`app.bootstrap`) on first use and cached on ``app.state``. Tests override
:func:`get_roles_service` (and the auth/rate-limit deps) to inject fakes so no real
Postgres/Redis/Celery wiring runs in unit tests.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.app_state import AppStateKeys
from app.bootstrap import build_roles_service
from app.schemas.auth import CurrentUser
from app.schemas.roles import RoleMiningAccepted, RoleRequirementsResponse
from app.schemas.skills_gap import SkillsGapResult
from app.security.dependencies import (
    get_rate_limit_service,
    rate_limit_exceeded_http,
    require_auth,
    resolve_optional_user,
)
from app.services.rate_limiting import RateLimitAction, RateLimitExceeded, RateLimitService
from app.services.roles import MiningAccepted, RolesService

router = APIRouter(prefix="/api/roles", tags=["roles"])


def get_roles_service(request: Request) -> RolesService:
    """FastAPI dependency: the app-scoped :class:`RolesService`, built once and cached.

    Delegates construction to the composition root (:func:`app.bootstrap.build_roles_service`)
    and caches the singleton on ``app.state``. Tests override this dependency to inject a fake so
    the real Postgres/Redis/Celery wiring never runs in unit tests.
    """
    service: RolesService | None = getattr(request.app.state, AppStateKeys.ROLES_SERVICE, None)
    if service is None:
        service = build_roles_service(request.app)
        setattr(request.app.state, AppStateKeys.ROLES_SERVICE, service)
    return service


def _rate_limit_subject(current_user: CurrentUser | None, request: Request) -> CurrentUser:
    """Resolve the identity the market-query rate limit is keyed on (§5.6 / §7).

    A present guest/user token keys on its own session/user (the normal per-session budget); an
    anonymous caller keys on client IP (``role="guest"``) so the shared corpus is still throttled
    per the guest policy without requiring an account. ``request.client`` is ``None`` only in
    exotic transports — fall back to a fixed bucket so the limiter always has a key.
    """
    if current_user is not None:
        return current_user
    client_ip = request.client.host if request.client is not None else "unknown"
    return CurrentUser(session_id=f"ip:{client_ip}", role="guest")


@router.get("/{role}/requirements")
async def get_role_requirements(
    role: str,
    request: Request,
    response: Response,
    current_user: CurrentUser | None = Depends(resolve_optional_user),
    service: RolesService = Depends(get_roles_service),
    rate_limiter: RateLimitService = Depends(get_rate_limit_service),
) -> RoleRequirementsResponse | RoleMiningAccepted:
    """Return a role's cached, cited requirement profile (no login required, §5.6).

    Rate-limited per session (or per IP when anonymous) reusing the message-action budget. A
    cache/DB hit returns the frequency-ranked requirements at ``200``; a role that has never been
    mined enqueues a background mine job and returns ``202`` with a ``task_id`` the client polls
    via ``GET /api/jobs/status/{task_id}`` (P5-06). Mining never runs on this request path (§7.5).
    """
    subject = _rate_limit_subject(current_user, request)
    try:
        await rate_limiter.enforce(RateLimitAction.MESSAGE, subject)
    except RateLimitExceeded as exc:
        raise rate_limit_exceeded_http(exc) from exc

    outcome = await service.get_requirements(role)
    if isinstance(outcome, MiningAccepted):
        response.status_code = status.HTTP_202_ACCEPTED
        return RoleMiningAccepted(task_id=outcome.task_id)
    return outcome.response


@router.get("/{role}/gap")
async def get_role_gap(
    role: str,
    response: Response,
    current_user: CurrentUser = Depends(require_auth),
    service: RolesService = Depends(get_roles_service),
) -> SkillsGapResult | RoleMiningAccepted:
    """Return the caller's skills gap against ``role`` (requires auth; guests rejected, §5.6).

    A gap needs a persisted profile, which only logged-in users have, so a guest
    (``user_id=None``) is a ``403`` (mirrors ``PUT /api/profile``, P5-05). The P6-05
    :class:`~app.services.skills_gap.SkillsGapService` does the diff: ``ok`` and
    ``profile_missing`` return ``200`` (the ``status`` field is self-describing — "upload a CV
    first" — never a 500), while a role never mined returns ``202`` + a mine-job handle so a cold
    ``/gap`` still makes forward progress without a second round-trip.
    """
    if current_user.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guests cannot compute a skills gap. Sign in and upload a CV first.",
        )

    outcome = await service.get_gap(current_user.user_id, role)
    if isinstance(outcome, MiningAccepted):
        response.status_code = status.HTTP_202_ACCEPTED
        return RoleMiningAccepted(task_id=outcome.task_id)
    return outcome
