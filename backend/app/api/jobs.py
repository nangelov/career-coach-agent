"""Jobs API — poll an async Celery task's progress (P5-06, §5.3 / §8).

A deliberately **thin** router (Router → Service → Repository, §8): it owns HTTP concerns only
— authN gating and offloading the blocking lookup — and delegates the Celery-state-to-API-shape
mapping to :class:`~app.services.jobs.JobStatusService`. It exposes the single generic endpoint

* ``GET /api/jobs/status/{task_id}`` — return the current status of *any* async job (CV parse
  now via P5-04's ``POST /api/profile/cv``; crawl/OCR later, §5.3). Not CV-specific by design.

**AuthZ — capability, not ownership.** The endpoint requires :func:`require_auth` (no anonymous
polling), but does **not** additionally check that the caller *enqueued* this ``task_id``. A
Celery ``task_id`` is an unguessable UUID4 handed back only to the request that enqueued the job,
so it functions as a bearer *capability*: knowing it is the authorization. Enforcing ownership on
top would mean persisting a ``task_id → user/session`` map (extra Redis state + TTL bookkeeping)
for negligible gain — and would need a guest branch anyway, since a guest gets a ``task_id`` too
(P5-04) but has no ``user_id`` to key on. Requiring auth (so no anonymous scanning) while
treating the id as a capability is the KISS choice and keeps the guest CV-upload flow working:
a guest polls their own job with the token they already hold. The task result carries only what
the id-holder already uploaded, so no cross-user data is exposed. (§7 AuthZ: users access only
their own data — here the unguessable id *is* the scope.)

Dependency wiring is lazy: the service is assembled by the composition root
(:mod:`app.bootstrap`) on first use and cached on ``app.state``. Tests override
:func:`get_job_status_service` to inject a fake so no real Celery/broker/Redis wiring runs.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request

from app.app_state import AppStateKeys
from app.bootstrap import build_job_status_service
from app.schemas.auth import CurrentUser
from app.schemas.jobs import JobStatusResponse
from app.security.dependencies import require_auth
from app.services.jobs import JobStatusService

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def get_job_status_service(request: Request) -> JobStatusService:
    """FastAPI dependency: the app-scoped :class:`JobStatusService`, built once and cached.

    Delegates construction to the composition root (:func:`app.bootstrap.build_job_status_service`)
    and caches the singleton on ``app.state``. Tests override this dependency to inject a fake so
    the real Celery result-backend wiring never runs in unit tests.
    """
    service: JobStatusService | None = getattr(
        request.app.state, AppStateKeys.JOB_STATUS_SERVICE, None
    )
    if service is None:
        service = build_job_status_service(request.app)
        setattr(request.app.state, AppStateKeys.JOB_STATUS_SERVICE, service)
    return service


@router.get("/status/{task_id}")
async def get_job_status(
    task_id: str,
    _current_user: CurrentUser = Depends(require_auth),
    service: JobStatusService = Depends(get_job_status_service),
) -> JobStatusResponse:
    """Return the current status of the async job identified by ``task_id`` (requires auth).

    The Celery result-backend lookup is synchronous (blocking Redis I/O), so it is offloaded to
    a worker thread to keep the event loop free. Mapping to the client-safe shape — including
    replacing any failure detail with a generic message — lives in the service. Auth is required
    but ownership is not separately checked: the unguessable ``task_id`` is the capability (see
    the module docstring).
    """
    return await asyncio.to_thread(service.get_status, task_id)
