"""CV-upload ingestion service — validate + enqueue the background parse job (§5.1 / §5.3).

The **policy** layer between the thin ``POST /api/profile/cv`` router and the Celery parse
task (:mod:`app.tasks.profile_ingest`). Following the Router → Service → Agent/Repository
layering (§8), all the non-HTTP business logic lives here:

* **Validate** the upload — non-empty, within :attr:`~app.config.Settings.CV_UPLOAD_MAX_BYTES`,
  and a supported CV format (PDF/DOCX/PPTX/image, keyed off the same
  :func:`~app.ingestion.formats.detect_format` the parser uses so the endpoint and the engine
  agree on what is parseable).
* **Enqueue** the parse task and return its ``task_id`` — the request path never parses
  (§5.3: slow document intelligence runs off the request path).

The actual enqueue is a narrow injected **port** (:class:`CvIngestEnqueuer`) so this service
has no import-time dependency on Celery: production wires the real
:func:`app.tasks.profile_ingest.enqueue_cv_ingest` (composition root), while unit tests inject
a fake that records the call and returns a canned id — no broker required. The file bytes are
base64-encoded here because the Celery task uses the JSON serializer (bytes are not
JSON-serializable); CV files are small and upload is rate-limited, so this is cheap.

Rejections are typed domain exceptions (:class:`ProfileUploadRejected` and subclasses) the
router maps to the right 4xx — the service never raises :class:`~fastapi.HTTPException`, so
HTTP status stays an API-layer concern.
"""

from __future__ import annotations

import base64
from typing import Protocol

from app.config import Settings, settings
from app.ingestion.formats import MEDIA_TYPE_EXTENSIONS, detect_format
from app.schemas.auth import CurrentUser

#: Supported CV upload formats (lower-cased, no leading dot) — mirrors the ingestion
#: format map (DRY) so the endpoint accepts exactly what the parser can handle, plus the
#: common extension aliases a browser may send (``jpeg`` / ``tif``).
ALLOWED_UPLOAD_FORMATS: frozenset[str] = frozenset(
    ext.lstrip(".") for ext in MEDIA_TYPE_EXTENSIONS.values()
) | {"jpeg", "tif"}


class ProfileUploadRejected(Exception):
    """Base: the upload was rejected before enqueue (a client error). Carries a ``reason``."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class EmptyUpload(ProfileUploadRejected):
    """The uploaded file had no bytes (→ 400)."""


class UploadTooLarge(ProfileUploadRejected):
    """The uploaded file exceeded :attr:`Settings.CV_UPLOAD_MAX_BYTES` (→ 413)."""


class UnsupportedUploadType(ProfileUploadRejected):
    """The file's format is not a supported CV format (→ 415)."""


class CvIngestEnqueuer(Protocol):
    """The narrow enqueue port the service depends on (no hard Celery import).

    Production is :func:`app.tasks.profile_ingest.enqueue_cv_ingest`; tests inject a fake.
    Returns the enqueued task's id (the handle the client polls, P5-06).
    """

    def __call__(
        self,
        *,
        content_b64: str,
        filename: str | None,
        media_type: str | None,
        user_id: str | None,
        session_id: str,
    ) -> str: ...


class ProfileIngestService:
    """Validate a CV upload and enqueue the background parse job (§5.1 / §5.3).

    A thin policy over the injected :class:`CvIngestEnqueuer`: nothing here touches HTTP or
    Celery directly. Built once per process by the composition root
    (:func:`app.bootstrap.build_profile_ingest_service`).
    """

    def __init__(
        self,
        enqueuer: CvIngestEnqueuer,
        *,
        max_upload_bytes: int,
    ) -> None:
        self._enqueuer = enqueuer
        self._max_upload_bytes = max_upload_bytes

    @classmethod
    def from_settings(
        cls, enqueuer: CvIngestEnqueuer, config: Settings = settings
    ) -> ProfileIngestService:
        """Build from application config (upload-size cap)."""
        return cls(enqueuer, max_upload_bytes=config.CV_UPLOAD_MAX_BYTES)

    @property
    def max_upload_bytes(self) -> int:
        """The configured upload-size cap (bytes) — the router reads it to reject oversized
        uploads *before* materializing the full body in memory (§9 abuse-prevention)."""
        return self._max_upload_bytes

    def submit(
        self,
        content: bytes,
        *,
        filename: str | None,
        media_type: str | None,
        user: CurrentUser,
    ) -> str:
        """Validate ``content`` and enqueue the parse job; return the Celery ``task_id``.

        The caller's identity is taken from the verified token (``user``), never from the
        request body (§7 AuthZ): a logged-in user's parsed profile/CV chunks are persisted
        under their ``user_id``; a guest (``user_id=None``) has the job run but its result is
        not persisted to Postgres (a guest has no ``users`` row to anchor a profile) — see the
        Celery task.

        Raises:
            EmptyUpload / UploadTooLarge / UnsupportedUploadType: the upload was rejected
                before enqueue (the router maps each to the matching 4xx).
        """
        self.validate(content, filename=filename, media_type=media_type)
        content_b64 = base64.b64encode(content).decode("ascii")
        return self._enqueuer(
            content_b64=content_b64,
            filename=filename,
            media_type=media_type,
            user_id=user.user_id,
            session_id=user.session_id,
        )

    def validate(self, content: bytes, *, filename: str | None, media_type: str | None) -> None:
        """Reject empty / oversized / unsupported uploads before any work is enqueued.

        Public so the router can validate the upload *before* charging the caller's rate-limit
        budget (§6.8): a rejected upload must not burn a guest's single per-session upload.
        Idempotent and cheap — :meth:`submit` re-runs it so the service stays safe if called
        directly (defense in depth).
        """
        if not content:
            raise EmptyUpload("The uploaded file is empty.")
        if len(content) > self._max_upload_bytes:
            raise UploadTooLarge(
                f"The uploaded file exceeds the maximum size of {self._max_upload_bytes} bytes."
            )
        fmt = detect_format(filename=filename, media_type=media_type)
        if fmt is None or fmt not in ALLOWED_UPLOAD_FORMATS:
            supported = ", ".join(sorted(ALLOWED_UPLOAD_FORMATS))
            raise UnsupportedUploadType(
                f"Unsupported file type. Upload a CV as one of: {supported}."
            )
