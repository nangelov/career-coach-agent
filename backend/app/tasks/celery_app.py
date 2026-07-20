"""Celery application + worker entrypoint.

Constructs the Celery app wired to Redis (broker + result backend) so that

    celery -A app.tasks.celery_app worker --loglevel=info

boots cleanly and can process tasks.

Task modules are made known to the worker via the `include` list of **string
module paths** — never by importing the task functions here. Each task module
imports `celery_app` from this module (e.g. ``from app.tasks.celery_app import
celery_app``), so importing them back here would create a circular import. The
worker discovers and imports the listed modules at startup, registering every
``@celery_app.task`` they define. Future async jobs (OCR/parse, crawl,
memory-learn — §5.3) simply append their module path to `include`.

Broker/backend URL is sourced from settings (REDIS_URL), never hard-coded.
"""

from __future__ import annotations

from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from app.config import settings

celery_app = Celery(
    "career_coach",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    # Lazy task-module discovery: the worker imports these modules by string path
    # and registers their @celery_app.task functions. No eager import of the task
    # objects here -> no circular import (the criterion behind P0-08).
    include=[
        "app.tasks.ping",
        "app.tasks.profile_ingest",
        "app.tasks.taxonomy",
        "app.tasks.market",
        "app.tasks.learning_resources",
        "app.tasks.memory_learn",
        "app.tasks.retention_purge",
    ],
)


@worker_process_init.connect(weak=False)
def _init_worker_observability(**_: Any) -> None:
    """Install OTel tracing + Sentry error tracking in each worker process (P11).

    Runs **after fork** (``worker_process_init``) so any background threads (the OTel exporter,
    the Sentry transport) belong to the worker process, not the pre-fork parent. Sets the global
    tracer provider + instruments Celery (each task body emits a span, child of the enqueuing
    request's trace when the producer propagated context, §6.26 / §7.8), and initialises Sentry
    so an unhandled task exception is reported (§6.24 / §7.7). Both are a no-op unless configured
    (``OTEL_ENABLED`` / ``SENTRY_DSN``); OTel exporters are PII-redacted and Sentry events are
    PII-scrubbed (§7.6). Imported lazily to keep task-module import light.
    """
    from app.observability import configure_sentry, configure_tracing, instrument_celery

    configure_tracing(settings)
    instrument_celery(settings)
    configure_sentry(settings)


celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Periodic (beat) schedule — the repo's first. The retention purge (S14, §6.18) runs
    # once daily; a 30-day retention window is coarse enough that daily granularity easily
    # satisfies it (no finer schedule needed). Fires at 03:00 UTC (off-peak). Requires a
    # running ``celery -A app.tasks.celery_app beat`` process (the compose ``beat`` service).
    beat_schedule={
        "retention-purge-daily": {
            "task": "tasks.retention_purge",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)
