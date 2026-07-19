"""message_feedback.message_id unique — one feedback row per message (P9-01).

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-18

Ahead of the P9-01 capture endpoint (``POST /api/messages/{message_id}/feedback``), the
per-message 👍/👎 store upserts feedback keyed on ``message_id`` (``INSERT ... ON CONFLICT
(message_id) DO UPDATE``) so resubmitting a rating replaces the same row rather than
duplicating it. A message has exactly one owner (one conversation → one session → one user),
so at most one feedback row per message is the correct invariant — but the P2-03 schema only
gave ``message_feedback.message_id`` a *non-unique* lookup index, which neither enforces that
invariant nor provides an ``ON CONFLICT`` arbiter.

Refinement encoded here:

* **Unique constraint ``uq_message_feedback_message_id`` replacing the plain lookup index.**
  The unique constraint enforces one-row-per-message *and* supplies the implicit index the old
  ``ix_message_feedback_message_id`` provided, so keeping both would leave a redundant index
  paying write cost — the single-column index is dropped and the unique constraint added
  (mirroring the P8-01 "replace redundant index" refinement).

No pgvector / functional indexes are involved, so no ``env.py`` autogenerate exclusions are
needed. This is a pure constraint/index change — no columns or data touched.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace the non-unique message_id index with a unique constraint (one row per message)."""
    op.drop_index(op.f("ix_message_feedback_message_id"), table_name="message_feedback")
    op.create_unique_constraint(
        "uq_message_feedback_message_id", "message_feedback", ["message_id"]
    )


def downgrade() -> None:
    """Restore the non-unique message_id lookup index."""
    op.drop_constraint("uq_message_feedback_message_id", "message_feedback", type_="unique")
    op.create_index(
        op.f("ix_message_feedback_message_id"),
        "message_feedback",
        ["message_id"],
        unique=False,
    )
