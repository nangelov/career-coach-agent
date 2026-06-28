"""Liveness task — proves the Celery broker/worker round-trip works.

This is the minimal task used by ``backend/scripts/check_celery.py`` to confirm
that a message can be enqueued on Redis, picked up by the worker, executed, and
its result returned via the result backend. Real async jobs (OCR/parse, crawl,
memory-learn — §5.3) arrive in P5+.
"""

from __future__ import annotations

from app.tasks.celery_app import celery_app


@celery_app.task(name="tasks.ping")
def ping() -> dict[str, bool]:
    """Return a trivial payload to confirm the worker executed the task."""
    return {"pong": True}
