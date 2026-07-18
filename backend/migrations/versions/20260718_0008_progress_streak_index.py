"""progress_entries streak index — composite (user_id, created_at) (P8-01).

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-18

Ahead of the P8 dashboard CRUD/summary API (``GET /api/dashboard``), the dashboard's
**streak / progress-trend** views (design §5.2 "progress charts, streaks, and % completion")
scan a single user's ``progress_entries`` log ordered by time — i.e. filter by ``user_id``
and group/order by ``created_at`` (e.g. distinct check-in days). The P2-05 schema only
indexed ``progress_entries.user_id`` on its own, which forces a sort of the matched rows for
those time-ordered aggregations.

Refinement encoded here:

* **Composite ``(user_id, created_at)`` index, replacing the single-column ``user_id``
  index.** The composite supports the streak query (``WHERE user_id = ? ORDER BY
  created_at``) directly, and — because ``user_id`` is the leading column — it *also* serves
  the plain per-user FK lookup the single-column index covered. Keeping both would leave a
  redundant index paying write cost on every append, so the old single-column index is
  dropped and the composite added.

No pgvector / functional indexes involved, so no ``env.py`` autogenerate exclusions are
needed. This is a **pure index change** — no columns, constraints, or data touched.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace the single-column user_id index with a (user_id, created_at) composite."""
    op.drop_index(op.f("ix_progress_entries_user_id"), table_name="progress_entries")
    op.create_index(
        "ix_progress_entries_user_id_created_at",
        "progress_entries",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Restore the single-column user_id index."""
    op.drop_index("ix_progress_entries_user_id_created_at", table_name="progress_entries")
    op.create_index(
        op.f("ix_progress_entries_user_id"),
        "progress_entries",
        ["user_id"],
        unique=False,
    )
