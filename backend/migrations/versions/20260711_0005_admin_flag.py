"""admin flag on users — real admin auth (P3-05).

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-11

Adds ``users.is_admin`` (design §7 AuthZ): the flag that gates admin-only endpoints, so
the v1 ``GET /get-feedback?key=<HF_TOKEN>`` "authenticate by matching the LLM API token in
the query string" pattern is replaced by a real access-control check — an authenticated
session (P3-02 session JWT) belonging to a user whose row has ``is_admin = true``.

Design decisions encoded here:

* **Boolean column, defaulted false, NOT NULL.** Every existing/new user is a non-admin by
  default; admin is a deliberate, out-of-band grant. ``server_default = false`` backfills
  the (few) existing rows without a data migration.
* **No self-service escalation.** No API route sets this column; it is granted only by a
  trusted operator with DB access. To make a user an admin, run (see docs/admin-access.md):

      UPDATE users SET is_admin = true WHERE email = 'operator@example.com';

  and revoke with ``SET is_admin = false``.

No pgvector / functional indexes are involved, so no ``env.py`` autogenerate exclusions are
needed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — add the ``users.is_admin`` flag (default false)."""
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema — drop the ``users.is_admin`` flag."""
    op.drop_column("users", "is_admin")
