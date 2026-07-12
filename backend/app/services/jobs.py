"""Job-status service — map a Celery task's Redis-backed state to the API shape (P5-06, §5.3).

The **policy** layer between the thin ``GET /api/jobs/status/{task_id}`` router and Celery's
result backend (Router → Service, §8). Celery already stores each task's state + progress meta
+ result in Redis (the ``celery_app`` backend is ``REDIS_URL``); this service reads that via an
:class:`~celery.result.AsyncResult` and translates it into the stable, client-facing
:class:`~app.schemas.jobs.JobStatusResponse` — collapsing Celery's internal state vocabulary
into a small enum, extracting the producer's progress meta, and — crucially — replacing any
failure detail with a **generic, client-safe message** so no internal exception text or
traceback ever reaches the client (§9).

The mapping is intentionally **generic to any Celery task** (not CV-specific): P5-04's CV parse
is the first producer, but P6's crawl/OCR jobs poll the same endpoint. A *custom* progress state
(anything that isn't a Celery built-in) is treated as "in progress", and its ``meta`` dict — if
present — supplies the ``stage``/``message``. So this needs no import of the CV task's state
names and keeps working as new producers add their own stages.

Testability: the only Celery seam is the injected :data:`AsyncResultFactory`, so a unit test
drives :meth:`JobStatusService.get_status` with a fake ``AsyncResult`` and **no live broker /
Redis**. Production wires the factory to ``AsyncResult(task_id, app=celery_app)`` (composition
root). The lookup itself is synchronous (Celery's result backend API is blocking), so the async
router offloads :meth:`get_status` to a worker thread rather than blocking the event loop.
"""

from __future__ import annotations

from typing import Any, Protocol

from celery import states

from app.schemas.jobs import JobStatusResponse

#: The single client-safe failure message. We deliberately never surface the task's exception
#: text: it can carry internal detail (file paths, provider errors, tokens embedded in a
#: message) and, more importantly, the client cannot act on it. A stable generic string keeps
#: the contract safe (§9) and the UI simple; the real cause is in the worker logs for operators.
SAFE_FAILURE_MESSAGE = "The job failed while processing. Please try again or contact support."

#: The client-safe message for a revoked/cancelled job (Celery's terminal REVOKED state).
CANCELLED_MESSAGE = "The job was cancelled."


class AsyncResultLike(Protocol):
    """The narrow slice of :class:`celery.result.AsyncResult` this service reads.

    Structural (duck-typed) so a real ``AsyncResult`` satisfies it and a test passes a trivial
    fake. Reading :attr:`state` fetches (and caches) the task meta from the result backend; a
    subsequent :attr:`result` read is served from that cache — one backend round-trip per poll.
    Neither property raises for a ``FAILURE`` state (only ``.get()`` re-raises), so reading them
    is safe here.
    """

    @property
    def state(self) -> str: ...

    @property
    def result(self) -> Any: ...


class AsyncResultFactory(Protocol):
    """Builds an :class:`AsyncResultLike` for a task id (the only Celery seam).

    Production: ``lambda task_id: AsyncResult(task_id, app=celery_app)``; tests inject a fake.
    """

    def __call__(self, task_id: str) -> AsyncResultLike: ...


def map_async_result(task_id: str, state: str, info: Any) -> JobStatusResponse:
    """Translate a Celery ``(state, info)`` pair into the client-facing status shape.

    Pure and Celery-backend-free — the unit-testable heart of the service. ``info`` is Celery's
    ``AsyncResult.result``: the return payload on ``SUCCESS``, the ``update_state`` ``meta`` dict
    on a custom progress state, the exception on ``FAILURE``, and ``None`` while ``PENDING``.

    Mapping (generic to any producer):

    * ``PENDING`` → ``pending`` (also what Celery reports for an **unknown/garbage** task id — a
      Redis result backend cannot distinguish "never enqueued" from "not started yet", so an
      unknown id polls as pending; documented, not special-cased).
    * ``SUCCESS`` → ``success`` with the result payload (only if it is a JSON object).
    * ``FAILURE`` → ``failure`` with a **generic** safe message (never the exception text).
    * ``REVOKED`` → ``failure`` with a cancelled message.
    * anything else (``STARTED``, ``RETRY``, or a custom stage like ``PARSING``) → ``in_progress``
      with the raw ``state`` plus any ``stage``/``message`` the producer put in ``meta``.
    """
    if state == states.SUCCESS:
        return JobStatusResponse(
            task_id=task_id,
            status="success",
            result=info if isinstance(info, dict) else None,
        )
    if state == states.FAILURE:
        return JobStatusResponse(task_id=task_id, status="failure", error=SAFE_FAILURE_MESSAGE)
    if state == states.REVOKED:
        return JobStatusResponse(task_id=task_id, status="failure", error=CANCELLED_MESSAGE)
    if state == states.PENDING:
        return JobStatusResponse(task_id=task_id, status="pending")

    # STARTED / RETRY / any producer-defined custom progress state (e.g. PARSING). The meta the
    # producer attached via update_state(meta=...) surfaces as stage/message when it is a dict.
    stage: str | None = None
    message: str | None = None
    if isinstance(info, dict):
        raw_stage = info.get("stage")
        raw_message = info.get("message")
        stage = raw_stage if isinstance(raw_stage, str) else None
        message = raw_message if isinstance(raw_message, str) else None
    return JobStatusResponse(
        task_id=task_id,
        status="in_progress",
        state=state,
        stage=stage,
        message=message,
    )


class JobStatusService:
    """Read a Celery task's current state and shape it into a :class:`JobStatusResponse`.

    A thin policy over the injected :data:`AsyncResultFactory`; nothing here touches HTTP. Built
    once per process by the composition root (:func:`app.bootstrap.build_job_status_service`).
    """

    def __init__(self, result_factory: AsyncResultFactory) -> None:
        self._result_factory = result_factory

    def get_status(self, task_id: str) -> JobStatusResponse:
        """Look up ``task_id`` and return its client-facing status.

        Synchronous by nature — Celery's result backend API is blocking — so the async router
        offloads this to a worker thread. One Redis round-trip: ``.state`` fetches and caches the
        task meta, ``.result`` reads from that cache.
        """
        async_result = self._result_factory(task_id)
        return map_async_result(task_id, async_result.state, async_result.result)
