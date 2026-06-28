#!/usr/bin/env python3
"""Smoke-test: prove the Celery broker -> worker -> result-backend round-trip.

Dev utility only (not wired into CI here — that is P0-09). Enqueues the
``tasks.ping`` task on Redis and waits for the worker to return its result:

    exit 0  +  "Celery OK"   -> task executed and returned {"pong": True}
    exit 1  +  "<error>"     -> timeout, connection error, or unexpected result

This mirrors ``check_pgvector.py``: it is intentionally self-contained and does
NOT import ``app.config`` (whose required secrets — HF_API_TOKEN, DATABASE_URL,
JWT_SECRET_KEY — would otherwise have to be present just to ping Redis). It
builds a throwaway Celery client straight from REDIS_URL and dispatches the task
by name (``send_task`` is the by-name equivalent of ``ping.delay()``), so it
does not need to import the task object either.

Connection resolution (first match wins):
  1. REDIS_URL                 (e.g. redis://redis:6379/0 inside compose)
  2. default                   redis://localhost:6379/0

No credentials are hard-coded. Run from the repo root after `docker compose up`
(so the broker and a worker are running):

    python backend/scripts/check_celery.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from celery import Celery

# Search order for a local .env: repo root, then backend/. Values already present
# in the real environment (e.g. inside compose) always win and are never
# overwritten. `.parents` is indexed defensively so the script never crashes at
# import time if it is run from an unexpected location.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2] if len(_HERE.parents) >= 3 else _HERE.parent
_ENV_CANDIDATES = (_REPO_ROOT / ".env", _REPO_ROOT / "backend" / ".env")

_DEFAULT_REDIS_URL = "redis://localhost:6379/0"
_PING_TASK_NAME = "tasks.ping"
_RESULT_TIMEOUT_SECONDS = 10


def _load_dotenv() -> None:
    """Minimal, dependency-free .env loader (KEY=VALUE lines; # comments ignored)."""
    for env_path in _ENV_CANDIDATES:
        if not env_path.is_file():
            continue
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            # Strip surrounding quotes if present; respect existing env values.
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


def _check() -> int:
    redis_url = os.environ.get("REDIS_URL", "").strip() or _DEFAULT_REDIS_URL

    # Throwaway client: same broker + result backend the worker uses, with the
    # json serializers the worker accepts.
    client = Celery(broker=redis_url, backend=redis_url)
    client.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
    )

    try:
        async_result = client.send_task(_PING_TASK_NAME)
        result = async_result.get(timeout=_RESULT_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — dev smoke-test: any failure -> exit 1
        print(f"Celery round-trip failed: {exc}", file=sys.stderr)
        return 1

    if result == {"pong": True}:
        print("Celery OK")
        return 0

    print(f"Celery returned unexpected result: {result!r}", file=sys.stderr)
    return 1


def main() -> None:
    _load_dotenv()
    sys.exit(_check())


if __name__ == "__main__":
    main()
