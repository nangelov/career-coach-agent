"""Async-job status contract (P5-06, §5.3 / §8) — generic Celery task-progress polling.

The wire shape for ``GET /api/jobs/status/{task_id}`` (§8 API table): a stable,
client-facing view over an arbitrary Celery task's Redis-backed state. Deliberately
**not** CV-specific — P5-04's CV parse is the first producer, but P6's crawl/OCR jobs reuse
the same endpoint (§5.3: *"jobs emit progress (state in Redis) that the UI polls"*), so the
vocabulary here is job/task-generic.

The client polls with the ``task_id`` it got back from whatever enqueued the job (e.g. the
:class:`~app.schemas.profile.CvUploadResponse` from ``POST /api/profile/cv``) and reads:

* :attr:`JobStatusResponse.status` — a small **stable** API enum the UI switches on,
  decoupled from Celery's internal state names so a Celery upgrade can't break the contract.
* :attr:`JobStatusResponse.state` / :attr:`stage` / :attr:`message` — the fine-grained
  in-progress signal (the producer's custom stage + human-readable message from its
  ``update_state(meta=...)``), surfaced verbatim for a "what is it doing now?" UI.
* :attr:`result` — present only on ``success``: the task's JSON result payload (for a CV job,
  the ``{profile, persisted, kb_document_id, chunk_count}`` shape P5-04 documented).
* :attr:`error` — present only on ``failure``: a **client-safe** generic message. Internal
  exception text / tracebacks are never surfaced (§9 — no leaking internals).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

#: The stable, client-facing job lifecycle. Intentionally coarser than Celery's internal
#: state set (``PENDING``/``STARTED``/custom/``SUCCESS``/``FAILURE``/``RETRY``/``REVOKED``): the
#: UI only needs "waiting / working / done / failed", and pinning a small enum here means an
#: internal Celery state change never leaks into the API contract.
JobStatusValue = Literal["pending", "in_progress", "success", "failure"]


class JobStatusResponse(BaseModel):
    """``GET /api/jobs/status/{task_id}`` body — one poll of a Celery task's progress.

    Generic across every async job (CV parse now; crawl/OCR later). ``status`` is the coarse
    stable enum the UI branches on; ``state``/``stage``/``message`` carry the producer's
    fine-grained progress; ``result`` is set only on success; ``error`` only on failure (and
    always a safe, generic message).
    """

    task_id: str = Field(..., description="The polled Celery task id.")
    status: JobStatusValue = Field(
        ..., description="Stable API-level lifecycle state the client switches on."
    )
    state: str | None = Field(
        default=None,
        description=(
            "Raw Celery state (e.g. a custom progress stage like 'PARSING'), surfaced verbatim "
            "for a fine-grained progress UI. None for a plain pending job."
        ),
    )
    stage: str | None = Field(
        default=None,
        description="Producer-supplied progress stage from the task meta (in-progress only).",
    )
    message: str | None = Field(
        default=None,
        description="Producer-supplied human-readable progress message (in-progress only).",
    )
    result: dict[str, Any] | None = Field(
        default=None,
        description="The task's JSON result payload — present only on success.",
    )
    error: str | None = Field(
        default=None,
        description="A client-safe failure message — present only on failure (never a traceback).",
    )
