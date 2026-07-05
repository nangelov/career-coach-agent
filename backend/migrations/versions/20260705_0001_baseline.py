"""baseline — empty starting point for the v2 schema.

Revision ID: 0001
Revises:
Create Date: 2026-07-05

This is a deliberate no-op baseline (P2-02): it establishes the Alembic revision
chain and the ``alembic_version`` bookkeeping table without creating any application
tables. The real tables land in later migrations:

* users / sessions            → P2-03
* knowledge base / memories   → P2-04
* dashboard                   → P2-05

The pgvector ``vector`` extension is NOT created here — it is bootstrapped once by
``migrations/init/01_enable_pgvector.sql`` (P0-07), which the Postgres container runs
before Alembic. Migrations assume the extension already exists.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — no-op baseline (no tables yet)."""


def downgrade() -> None:
    """Downgrade schema — no-op baseline."""
