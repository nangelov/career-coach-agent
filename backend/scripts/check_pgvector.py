#!/usr/bin/env python3
"""Smoke-test: verify the pgvector `vector` extension is enabled in Postgres.

Dev utility only (not wired into CI here — that is P0-09). Connects to Postgres
using credentials from the environment / a local `.env`, queries `pg_extension`,
and reports the result via exit code:

    exit 0  +  "pgvector OK"      -> extension present
    exit 1  +  "pgvector MISSING" -> extension absent
    exit 2  +  "<connection error>" -> could not connect

Connection resolution (first match wins):
  1. DATABASE_URL              (SQLAlchemy-style `+asyncpg`/`+psycopg` suffixes are
                                stripped automatically so asyncpg accepts the DSN)
  2. POSTGRES_* parts          POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB,
                               with POSTGRES_HOST (default "localhost") and
                               POSTGRES_PORT (default 5432).

No credentials are hard-coded. Run from the repo root after `docker compose up`:

    python backend/scripts/check_pgvector.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

# Search order for a local .env: repo root, then backend/. Values already present
# in the real environment (e.g. inside compose) always win and are never overwritten.
# `.parents` is indexed defensively so the script never crashes at import time if it
# is run from an unexpected location (e.g. copied to a shallow path in a container).
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2] if len(_HERE.parents) >= 3 else _HERE.parent
_ENV_CANDIDATES = (_REPO_ROOT / ".env", _REPO_ROOT / "backend" / ".env")


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


def _resolve_dsn() -> str:
    """Build a plain `postgresql://` DSN asyncpg can consume."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        # asyncpg wants the bare driver scheme, not SQLAlchemy's `postgresql+asyncpg`.
        return database_url.replace("postgresql+asyncpg", "postgresql").replace(
            "postgresql+psycopg", "postgresql"
        )

    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")
    db = os.environ.get("POSTGRES_DB")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")

    missing = [
        name
        for name, val in (
            ("POSTGRES_USER", user),
            ("POSTGRES_PASSWORD", password),
            ("POSTGRES_DB", db),
        )
        if not val
    ]
    if missing:
        raise RuntimeError(
            "No DATABASE_URL set and missing Postgres parts: "
            + ", ".join(missing)
            + ". Set them in .env or the environment."
        )
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


async def _check() -> int:
    try:
        dsn = _resolve_dsn()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        conn = await asyncpg.connect(dsn)
    except (OSError, asyncpg.PostgresError) as exc:
        print(f"could not connect to Postgres: {exc}", file=sys.stderr)
        return 2

    try:
        extname = await conn.fetchval("SELECT extname FROM pg_extension WHERE extname = 'vector';")
    finally:
        await conn.close()

    if extname == "vector":
        print("pgvector OK")
        return 0

    print("pgvector MISSING", file=sys.stderr)
    return 1


def main() -> None:
    _load_dotenv()
    sys.exit(asyncio.run(_check()))


if __name__ == "__main__":
    main()
