"""Profile API request/response contracts (P5-04, §5.1 / §9).

This module owns the wire shapes for the profile surface. P5-04 ships only the CV-upload
acknowledgement (:class:`CvUploadResponse`); the structured-profile read/update bodies
(``GET/PUT /api/profile``) arrive with P5-05.

Kept independent of the ingestion layer (``app.ingestion.profile.ProfileSchema`` is the
*internal* structured shape the Celery task persists into ``profiles.data``): the upload
endpoint returns **only** an async job handle, never the parsed profile, because parsing
runs off the request path (§5.3 — *"enqueue a task and stream a 'working…' state instead of
blocking the turn"*). The client polls ``GET /api/jobs/status/{task_id}`` (P5-06) with the
returned ``task_id`` to observe progress and collect the result.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CvUploadResponse(BaseModel):
    """``POST /api/profile/cv`` (HTTP 202) body — the async parse-job handle.

    Returned immediately after the upload is validated and enqueued; parsing itself runs in
    a Celery worker (§5.3). ``task_id`` is the Celery task id the client polls via
    ``GET /api/jobs/status/{task_id}`` (P5-06) to watch progress (Redis-backed state) and
    retrieve the structured profile once the job succeeds.
    """

    task_id: str = Field(..., description="Celery task id to poll for progress/result (P5-06).")
    status: Literal["accepted"] = Field(
        default="accepted",
        description="Always 'accepted' — the file was validated and the parse job enqueued.",
    )
