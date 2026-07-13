"""consent columns on users — ToS/privacy acceptance gate (SEC-06).

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-13

Adds ``users.consent_policy_version`` + ``users.consent_accepted_at`` (design §6.22 / §7.6):
no session is minted without acceptance of the Terms of Service + privacy notice, and for an
SSO user the acceptance is recorded against their row with the **policy version + timestamp**
so a policy bump can re-prompt (a returning user whose stored version no longer matches
``settings.CONSENT_POLICY_VERSION`` re-accepts on their next login, which overwrites these).

Design decisions encoded here:

* **Both columns nullable, no server default.** A ``users`` row may legitimately exist before
  any consent is recorded (an out-of-band admin seed, a pre-existing row); the SSO login flow
  writes both on every login. Existing rows backfill to ``NULL`` (unknown / pre-gate) with no
  data migration.
* **Guests get nothing here.** A guest is Redis-only (§4/§6.18) — per-session consent lives on
  the transient Redis session record, never in Postgres — so no guest-facing column exists.

No pgvector / functional indexes are involved, so no ``env.py`` autogenerate exclusions are
needed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — add the two nullable consent columns to ``users``."""
    op.add_column(
        "users",
        sa.Column("consent_policy_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("consent_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema — drop the consent columns."""
    op.drop_column("users", "consent_accepted_at")
    op.drop_column("users", "consent_policy_version")
