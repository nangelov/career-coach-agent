"""market intelligence — role_profiles + job_postings table group (P6-02).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-13

Rescopes the P2-05 ``jobs`` table into the P6 *market-intelligence* group (design §5.6
"role requirements, not a job board") and adds the durable ``role_profiles`` artifact.

Design decisions encoded here:

* **``jobs`` → ``job_postings`` (raw evidence only, §5.6).** The table is renamed; its
  ``(source, external_id)`` dedup key and its ``source_url`` index are renamed to match.
  Postings are internal evidence for aggregation, never a browsable surface.
* **Per-posting ``match_score`` is dropped (§5.6, P6).** "Match scoring" now means
  ``user profile ↔ role_profile`` (the skills gap) — computed on demand, not stored on a
  posting. The column is removed.
* **New posting columns.** ``target_role`` (the canonical role a posting was mined as
  evidence for) and ``expires_at`` (TTL cache expiry, §5.6) — both NOT NULL and indexed
  (a periodic sweep queries expired rows; aggregation reads all postings for a role). They
  are added with a transient ``server_default`` to backfill any cached rows, then the
  default is dropped so the final schema matches the ORM model (no server default).
* **``role_profiles`` — the global, non-personal artifact (§5.6).** One row per
  ``canonical_role`` (UNIQUE — extraction happens once per role, reused across users),
  with an optional taxonomy id, aggregated ``requirements``/``sources`` JSONB (every
  requirement cited), an ``evidence_count`` and a ``refreshed_at`` TTL marker. **No
  ``user_id`` / no cascade** — a GDPR user-delete (§7.6) never touches it.

Third-party PII stripping on postings (§7.6) is enforced in the P6-04 ingestion code; this
migration only provides the schema that supports it. No pgvector / functional indexes are
in this group, so no ``env.py`` autogenerate exclusions are needed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — rename jobs→job_postings, reshape it, add role_profiles."""
    # 1. Rename the table and its dependent constraint/index/pk to the new name.
    op.rename_table("jobs", "job_postings")
    op.execute(
        "ALTER TABLE job_postings "
        "RENAME CONSTRAINT uq_jobs_source_external_id "
        "TO uq_job_postings_source_external_id"
    )
    op.execute("ALTER INDEX ix_jobs_source_url RENAME TO ix_job_postings_source_url")
    op.execute("ALTER INDEX jobs_pkey RENAME TO job_postings_pkey")

    # 2. Drop per-posting match scoring (§5.6 — match = user△role_profile, computed).
    op.drop_column("job_postings", "match_score")

    # 3. Add the market-evidence columns. NOT NULL with a transient server_default so any
    #    cached rows backfill; then drop the default to match the ORM (no default).
    op.add_column(
        "job_postings",
        sa.Column("target_role", sa.String(length=512), nullable=False, server_default=""),
    )
    op.alter_column("job_postings", "target_role", server_default=None)
    op.create_index(
        op.f("ix_job_postings_target_role"), "job_postings", ["target_role"], unique=False
    )
    op.add_column(
        "job_postings",
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.alter_column("job_postings", "expires_at", server_default=None)
    op.create_index(
        op.f("ix_job_postings_expires_at"), "job_postings", ["expires_at"], unique=False
    )

    # 4. The durable, global role artifact (§5.6). No user_id / no cascade.
    op.create_table(
        "role_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        # Normalized/taxonomy-matched title — one profile per canonical role (UNIQUE).
        sa.Column("canonical_role", sa.String(length=512), nullable=False),
        # ESCO / O*NET occupation id, when the role matched one.
        sa.Column("taxonomy_id", sa.String(length=128), nullable=True),
        # skill → {"frequency", "weight", "evidence": [...]} — every requirement cited.
        sa.Column(
            "requirements",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        # Source identifiers / urls contributing to this profile.
        sa.Column(
            "sources",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("evidence_count", sa.Integer(), server_default="0", nullable=False),
        # TTL staleness marker (§5.6) — nullable until the first aggregation runs.
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        # One profile per canonical role — reused across all users (§5.6).
        sa.UniqueConstraint("canonical_role"),
    )


def downgrade() -> None:
    """Downgrade schema — drop role_profiles, restore the P2-05 ``jobs`` shape."""
    op.drop_table("role_profiles")

    op.drop_index(op.f("ix_job_postings_expires_at"), table_name="job_postings")
    op.drop_column("job_postings", "expires_at")
    op.drop_index(op.f("ix_job_postings_target_role"), table_name="job_postings")
    op.drop_column("job_postings", "target_role")

    # Re-add the dropped placeholder column.
    op.add_column("job_postings", sa.Column("match_score", sa.Float(), nullable=True))

    # Reverse the rename (table + dependent constraint/index/pk names).
    op.execute("ALTER INDEX job_postings_pkey RENAME TO jobs_pkey")
    op.execute("ALTER INDEX ix_job_postings_source_url RENAME TO ix_jobs_source_url")
    op.execute(
        "ALTER TABLE job_postings "
        "RENAME CONSTRAINT uq_job_postings_source_external_id "
        "TO uq_jobs_source_external_id"
    )
    op.rename_table("job_postings", "jobs")
