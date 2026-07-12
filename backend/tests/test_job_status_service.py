"""Unit tests for the job-status mapping (P5-06, §5.3) — no Celery broker/Redis required.

Drives :func:`~app.services.jobs.map_async_result` and :class:`~app.services.jobs.JobStatusService`
with a trivial fake ``AsyncResult`` (just ``state`` + ``result``), so the Celery-state → API-shape
translation is exercised end-to-end offline. Deliberately tests against the **exact** state names,
progress ``meta`` keys, and result payload shape that P5-04's real producer
(:mod:`app.tasks.profile_ingest`) emits, so the consumer provably matches the producer with no
rework on that side.
"""

from __future__ import annotations

from typing import Any

from celery import states

from app.services.jobs import (
    CANCELLED_MESSAGE,
    SAFE_FAILURE_MESSAGE,
    JobStatusService,
    map_async_result,
)
from app.tasks.profile_ingest import (
    STATE_PARSING,
    STATE_PERSISTING,
    STATE_STRUCTURING,
)


class FakeAsyncResult:
    """Minimal :class:`celery.result.AsyncResult` stand-in (the two properties read)."""

    def __init__(self, state: str, result: Any = None) -> None:
        self._state = state
        self._result = result

    @property
    def state(self) -> str:
        return self._state

    @property
    def result(self) -> Any:
        return self._result


def _service_for(state: str, result: Any = None) -> JobStatusService:
    return JobStatusService(lambda task_id: FakeAsyncResult(state, result))


def test_pending_maps_to_pending() -> None:
    resp = map_async_result("t1", states.PENDING, None)
    assert resp.task_id == "t1"
    assert resp.status == "pending"
    assert resp.state is None
    assert resp.stage is None
    assert resp.result is None
    assert resp.error is None


def test_unknown_task_id_reports_pending() -> None:
    # Celery cannot distinguish an unknown/garbage id from a not-yet-started task in a Redis
    # result backend — both surface as PENDING. Documented behavior: we report it as pending.
    resp = _service_for(states.PENDING, None).get_status("garbage-id")
    assert resp.status == "pending"
    assert resp.task_id == "garbage-id"


def test_started_maps_to_in_progress() -> None:
    resp = map_async_result("t1", states.STARTED, None)
    assert resp.status == "in_progress"
    assert resp.state == states.STARTED


def test_custom_parsing_stage_surfaces_meta() -> None:
    # The exact meta shape the producer attaches at the PARSING stage.
    meta = {"stage": "parsing", "message": "Extracting document text."}
    resp = map_async_result("t1", STATE_PARSING, meta)
    assert resp.status == "in_progress"
    assert resp.state == STATE_PARSING
    assert resp.stage == "parsing"
    assert resp.message == "Extracting document text."


def test_each_producer_progress_state_is_in_progress() -> None:
    for state, stage in (
        (STATE_PARSING, "parsing"),
        (STATE_STRUCTURING, "structuring"),
        (STATE_PERSISTING, "persisting"),
    ):
        resp = map_async_result("t1", state, {"stage": stage, "message": "..."})
        assert resp.status == "in_progress"
        assert resp.stage == stage


def test_success_returns_result_payload() -> None:
    # The exact result shape run_cv_ingestion returns (the "P5-06-consumable" contract).
    payload = {
        "profile": {"skills": ["Python"]},
        "persisted": True,
        "kb_document_id": "doc-123",
        "chunk_count": 4,
    }
    resp = _service_for(states.SUCCESS, payload).get_status("t1")
    assert resp.status == "success"
    assert resp.result == payload
    assert resp.error is None


def test_success_with_non_dict_result_is_dropped() -> None:
    # Defensive: a non-object result never smuggles a bare scalar into the typed field.
    resp = map_async_result("t1", states.SUCCESS, "not-a-dict")
    assert resp.status == "success"
    assert resp.result is None


def test_failure_returns_safe_generic_message_not_exception_text() -> None:
    secret = "boom: /internal/path/token=abc123 traceback line"
    resp = _service_for(states.FAILURE, RuntimeError(secret)).get_status("t1")
    assert resp.status == "failure"
    assert resp.error == SAFE_FAILURE_MESSAGE
    # No internal exception text / traceback leaks into any field.
    assert secret not in (resp.error or "")
    assert resp.result is None
    assert resp.message is None


def test_revoked_maps_to_failure_with_cancelled_message() -> None:
    resp = map_async_result("t1", states.REVOKED, None)
    assert resp.status == "failure"
    assert resp.error == CANCELLED_MESSAGE


def test_service_reads_state_and_result_via_factory() -> None:
    # The service builds the AsyncResult from the injected factory using the given task id.
    seen: list[str] = []

    def factory(task_id: str) -> FakeAsyncResult:
        seen.append(task_id)
        return FakeAsyncResult(STATE_STRUCTURING, {"stage": "structuring", "message": "m"})

    resp = JobStatusService(factory).get_status("task-42")
    assert seen == ["task-42"]
    assert resp.task_id == "task-42"
    assert resp.stage == "structuring"
