"""Alembic migration environment (async SQLAlchemy).

Wires Alembic to the same foundation the app uses (design §4 / §8):

* **Connection config comes from the app's settings, not a hardcoded URL.** We read
  ``DATABASE_URL`` from :class:`app.config.Settings` — the *same* settings object the
  running app uses — so Alembic and the app can never drift on which database they
  talk to. ``alembic.ini`` intentionally omits ``sqlalchemy.url``; it is injected here.
* **``target_metadata`` is ``Base.metadata``** from :mod:`app.repositories.postgres` —
  the one declarative base every v2 ORM model (P2-03/04/05) subclasses — so
  ``alembic revision --autogenerate`` sees the full schema once models land.
* **Async engine.** The app talks to Postgres over ``postgresql+asyncpg`` via a
  SQLAlchemy ``AsyncEngine``; migrations use the async template
  (``asyncio.run`` + ``async_engine_from_config``) so the same DSN/driver works here.

The pgvector extension is **not** created here — it is bootstrapped once by
``backend/migrations/init/01_enable_pgvector.sql`` (P0-07), mounted into the Postgres
container's ``/docker-entrypoint-initdb.d/`` and run before Alembic ever executes.
Migrations therefore assume the ``vector`` extension already exists.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import the ORM model package for its side effect: every model module registers its
# table on ``Base.metadata``, which is what ``--autogenerate`` diffs against. Without
# this import the metadata would be empty and autogenerate would propose dropping every
# table. Kept as a bare side-effecting import (models are referenced via the metadata).
import app.repositories.models  # noqa: E402, F401
from app.config import settings
from app.repositories.postgres import Base

# The Alembic Config object provides access to the values in alembic.ini.
config = context.config

# Interpret the ini file for Python logging (sets up loggers).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the connection URL from the app's settings (single source of truth) rather
# than reading a hardcoded/duplicated string from alembic.ini.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Autogenerate target: the shared declarative Base's metadata. Empty until P2-03
# adds the first ORM models, at which point --autogenerate produces real migrations.
target_metadata = Base.metadata

# Functional/expression indexes that Alembic cannot derive from the ORM and therefore
# cannot round-trip during autogenerate. They are created by hand (raw SQL) inside the
# migrations and excluded from the autogenerate comparison so drift checks stay clean —
# without this, autogenerate would see them reflected from the DB, fail to match them to
# any ``mapped_column`` index, and spuriously propose dropping them every run.
#
# P2-04: the pgvector embedding vectors are ``vector(4096)``; 4096 exceeds pgvector's
# HNSW dimension cap (2000 for ``vector``, 4000 for ``halfvec``), so the ANN indexes use
# the documented high-dim pattern — an HNSW index over ``binary_quantize(embedding)::
# bit(4096)`` (``bit`` supports up to 64000 dims). That is a functional expression index,
# not expressible via ``mapped_column``, hence the manual management + exclusion here.
_UNMODELED_INDEXES = frozenset(
    {
        "ix_kb_chunks_embedding_hnsw",
        "ix_user_memories_embedding_hnsw",
    }
)


def include_object(
    obj: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Autogenerate filter: skip hand-managed functional indexes (see above)."""
    if type_ == "index" and name in _UNMODELED_INDEXES:
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout, no DBAPI connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure the context against a live (sync-facing) connection and migrate."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine from the config and run migrations over one connection."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (async engine)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
