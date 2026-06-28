# tasks — Celery app + async tasks (OCR/parse, crawl, memory-learn) + worker entry
#
# Re-export the Celery instance as `app` so it can be referenced as
# `app.tasks.app` if needed; the worker entrypoint targets `app.tasks.celery_app`.
from app.tasks.celery_app import celery_app as app

__all__ = ["app"]
