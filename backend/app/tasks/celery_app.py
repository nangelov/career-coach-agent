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

from celery import Celery

from app.config import settings

celery_app = Celery(
    "career_coach",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    # Lazy task-module discovery: the worker imports these modules by string path
    # and registers their @celery_app.task functions. No eager import of the task
    # objects here -> no circular import (the criterion behind P0-08).
    include=["app.tasks.ping"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)
