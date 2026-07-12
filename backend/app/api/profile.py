"""Profile API — CV upload (§5.1) plus structured-profile read/edit (§4/§8).

This router is deliberately **thin** (Router → Service → Agent/Repository, §8): it owns HTTP
concerns only — authN/rate-limit gating, request/response shaping, and mapping typed
rejections to 4xx — and delegates all business logic to injected ports. It serves the whole
``/api/profile`` surface:

* ``POST /api/profile/cv`` — upload a CV; the actual parse runs off the request path in a
  Celery worker (§5.3), so the endpoint validates, enqueues, and returns a 202 job handle. The
  logic lives in :class:`~app.services.profile_ingest.ProfileIngestService` (the v1
  ``/pdp-generator`` parsed synchronously — v2 must not).
* ``GET /api/profile`` — read the caller's structured profile (the P5-03
  :class:`~app.ingestion.profile.ProfileSchema` the parse produced), so the frontend (P5-07)
  and agents reuse it across chats **without re-uploading a CV** (§4). A caller with no profile
  yet (fresh account or guest) gets an **empty** profile at ``200`` rather than a ``404`` —
  the friendlier contract for a view/edit UI that always renders a (possibly empty) form.
* ``PUT /api/profile`` — replace the caller's profile with a client-supplied body validated
  against :class:`ProfileSchema` (FastAPI rejects a malformed body with ``422``), the way a
  user edits their auto-parsed profile (P5-07). A guest is rejected (``403``): a profile is
  anchored to a ``users`` row and a guest has none.

Every endpoint is **user-scoped** (§7 AuthZ): the target row is always the verified token
subject's own — there is no path/query ``user_id`` a caller could point at another user.

Dependency wiring is lazy: each port is assembled by the composition root
(:mod:`app.bootstrap`) on first use and cached on ``app.state``. Tests override the
``get_profile_*`` dependencies to inject fakes, so no real broker/Celery/Postgres wiring runs
in unit tests.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.exceptions import HTTPException

from app.app_state import AppStateKeys
from app.bootstrap import build_profile_ingest_service, build_profile_store
from app.ingestion.profile import ProfileSchema
from app.schemas.auth import CurrentUser
from app.schemas.profile import CvUploadResponse
from app.security.dependencies import (
    get_rate_limit_service,
    rate_limit_exceeded_http,
    require_auth,
)
from app.services.profile_ingest import (
    EmptyUpload,
    ProfileIngestService,
    ProfileUploadRejected,
    UnsupportedUploadType,
    UploadTooLarge,
)
from app.services.profile_store import ProfileStore
from app.services.rate_limiting import RateLimitAction, RateLimitExceeded, RateLimitService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["profile"])

#: Bounded read granularity (bytes) — the upload is pulled in chunks so an oversized (or
#: size-lying) body is rejected mid-read before more than the cap is ever held in memory.
_READ_CHUNK_BYTES = 1024 * 1024


def get_profile_ingest_service(request: Request) -> ProfileIngestService:
    """FastAPI dependency: the app-scoped :class:`ProfileIngestService`, built once and cached.

    Delegates construction to the composition root
    (:func:`app.bootstrap.build_profile_ingest_service`) and caches the singleton on
    ``app.state``. Tests override this dependency to inject a fake so no real Celery/broker
    wiring runs in unit tests.
    """
    service: ProfileIngestService | None = getattr(
        request.app.state, AppStateKeys.PROFILE_INGEST_SERVICE, None
    )
    if service is None:
        service = build_profile_ingest_service(request.app)
        setattr(request.app.state, AppStateKeys.PROFILE_INGEST_SERVICE, service)
    return service


def get_profile_store(request: Request) -> ProfileStore:
    """FastAPI dependency: the app-scoped :class:`ProfileStore`, built once and cached.

    Delegates construction to the composition root (:func:`app.bootstrap.build_profile_store`)
    and caches the singleton on ``app.state``. Tests override this dependency to inject an
    in-memory store so the real Postgres wiring never runs in unit tests.
    """
    store: ProfileStore | None = getattr(request.app.state, AppStateKeys.PROFILE_STORE, None)
    if store is None:
        store = build_profile_store(request.app)
        setattr(request.app.state, AppStateKeys.PROFILE_STORE, store)
    return store


async def _read_within_cap(file: UploadFile, max_bytes: int) -> bytes:
    """Read the upload without ever holding more than ``max_bytes`` in memory.

    Enforces the size cap *before* the body is materialized (C1 / §9 abuse-prevention): first a
    cheap guard on ``file.size`` (populated by Starlette during the multipart parse) short-
    circuits an oversized upload before a single byte is read, then a bounded chunked read
    rejects on overflow so an absent/understated ``size`` still cannot blow past the cap. Raises
    the typed :class:`UploadTooLarge` (the router maps it to 413) — this is the primary guard,
    not the post-read length check in the service.
    """
    if file.size is not None and file.size > max_bytes:
        raise UploadTooLarge(f"The uploaded file exceeds the maximum size of {max_bytes} bytes.")
    chunks: list[bytes] = []
    total = 0
    while data := await file.read(_READ_CHUNK_BYTES):
        total += len(data)
        if total > max_bytes:
            raise UploadTooLarge(
                f"The uploaded file exceeds the maximum size of {max_bytes} bytes."
            )
        chunks.append(data)
    return b"".join(chunks)


def _rejected_to_http(exc: ProfileUploadRejected) -> HTTPException:
    """Map a typed upload rejection to the right 4xx (HTTP status stays an API concern)."""
    if isinstance(exc, UploadTooLarge):
        # 413 Content Too Large — literal to stay stable across Starlette's constant rename.
        code = 413
    elif isinstance(exc, UnsupportedUploadType):
        code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    elif isinstance(exc, EmptyUpload):
        code = status.HTTP_400_BAD_REQUEST
    else:  # pragma: no cover - defensive: base class maps to a generic 400
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=exc.reason)


@router.post("/profile/cv", status_code=status.HTTP_202_ACCEPTED)
async def upload_cv(
    file: UploadFile = File(..., description="CV file (PDF/DOCX/PPTX/image)."),
    current_user: CurrentUser = Depends(require_auth),
    service: ProfileIngestService = Depends(get_profile_ingest_service),
    rate_limiter: RateLimitService = Depends(get_rate_limit_service),
) -> CvUploadResponse:
    """Upload a CV, enqueue the background parse job, and return its ``task_id`` (HTTP 202).

    Requires a valid bearer token (guest or user). Order of operations matters:

    1. The body is read under a size cap (:func:`_read_within_cap`) — an oversized upload is
       rejected with ``413`` *before* the full file is materialized in memory, so it can't OOM
       the API process (§9 abuse-prevention).
    2. The file is validated (empty / type) — rejected uploads map to ``400`` (empty), ``413``
       (too large), or ``415`` (unsupported type).
    3. Only a **known-valid** upload is charged against the caller's document-upload budget
       (guest: 1 per session; user: generous per-window, §6.8/§7); an over-budget caller gets
       ``429``. Validating before charging means a fat-fingered bad file doesn't permanently
       burn a guest's single upload.
    4. The file is enqueued to a Celery task and this returns **immediately** with the job
       handle the client polls via ``GET /api/jobs/status/{task_id}`` (P5-06) — parsing itself
       runs off the request path (§5.3).
    """
    try:
        content = await _read_within_cap(file, service.max_upload_bytes)
        service.validate(content, filename=file.filename, media_type=file.content_type)
    except ProfileUploadRejected as exc:
        raise _rejected_to_http(exc) from exc

    # Charge the upload budget only after the file is known-valid, so a rejected upload never
    # consumes a guest's single per-session upload (§6.8).
    try:
        await rate_limiter.enforce(RateLimitAction.UPLOAD, current_user)
    except RateLimitExceeded as exc:
        raise rate_limit_exceeded_http(exc) from exc

    task_id = service.submit(
        content,
        filename=file.filename,
        media_type=file.content_type,
        user=current_user,
    )
    return CvUploadResponse(task_id=task_id)


@router.get("/profile")
async def get_profile(
    current_user: CurrentUser = Depends(require_auth),
    store: ProfileStore = Depends(get_profile_store),
) -> ProfileSchema:
    """Return the caller's own structured profile, reused across chats (§4/§8).

    User-scoped (§7 AuthZ): the profile fetched is always the verified token subject's own —
    there is no ``user_id`` in the path/query for a caller to point at someone else. When the
    caller has no profile yet — a fresh account that never uploaded a CV, or a guest (who has
    no persisted profile at all) — this returns an **empty** :class:`ProfileSchema` at ``200``
    rather than a ``404``, so the P5-07 view/edit UI always has a renderable shape.

    A guest (``user_id=None``) short-circuits to the empty profile without a DB lookup: a guest
    has no ``users`` row, so there is never a profile to fetch.
    """
    if current_user.user_id is None:
        return ProfileSchema()
    profile = await store.get(current_user.user_id)
    return profile if profile is not None else ProfileSchema()


@router.put("/profile")
async def put_profile(
    profile: ProfileSchema,
    current_user: CurrentUser = Depends(require_auth),
    store: ProfileStore = Depends(get_profile_store),
) -> ProfileSchema:
    """Replace the caller's structured profile with a validated body (§4/§8) — user only.

    The body is validated against :class:`ProfileSchema` by FastAPI before this runs, so a
    malformed payload is a ``422`` and never reaches the store. The upsert targets the verified
    token subject's own row (§7 AuthZ) — no ``user_id`` is accepted from the client.

    A **guest** (``user_id=None``) is rejected with ``403``: a profile is anchored to a
    ``users`` row via a foreign key and a guest has none, so there is nothing to persist
    against. The message points them at signing in (mirrors the guest posture the P5-04 upload
    task documented). Returns the stored profile on success.
    """
    if current_user.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guests cannot save a profile. Sign in to store and edit your profile.",
        )
    return await store.upsert(current_user.user_id, profile)
