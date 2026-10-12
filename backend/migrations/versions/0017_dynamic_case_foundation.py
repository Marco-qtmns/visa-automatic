"""add provider-neutral canonical value revision ledger

Revision ID: 0017_dynamic_case_foundation
Revises: 0016_import_review_state
Create Date: 2026-10-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0017_dynamic_case_foundation"
down_revision: str | None = "0016_import_review_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    candidate_columns = (
        {column["name"] for column in inspector.get_columns("fact_extraction_candidates")}
        if inspector.has_table("fact_extraction_candidates") else set()
    )
    if inspector.has_table("fact_extraction_candidates") and "assertion_type" not in candidate_columns:
        op.add_column(
            "fact_extraction_candidates",
            sa.Column("assertion_type", sa.String(length=16), nullable=False, server_default="explicit"),
        )
    if inspector.has_table("canonical_value_revisions"):
        return
    op.create_table(
        "canonical_value_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("field_path", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("original_value_json", sa.JSON(), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_version", sa.String(length=64), nullable=True),
        sa.Column("review_state", sa.String(length=24), nullable=False),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "review_state IN ('unreviewed', 'confirmed', 'corrected', 'needs_review', 'rejected')",
            name="canonical_value_revision_review_state_valid",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "field_path", "revision", name="uq_canonical_value_revision"),
    )
    op.create_index(
        "ix_canonical_value_revisions_case_field",
        "canonical_value_revisions",
        ["case_id", "field_path"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("canonical_value_revisions"):
        op.drop_index(
            "ix_canonical_value_revisions_case_field",
            table_name="canonical_value_revisions",
        )
        op.drop_table("canonical_value_revisions")
    if inspector.has_table("fact_extraction_candidates"):
        candidate_columns = {column["name"] for column in inspector.get_columns("fact_extraction_candidates")}
        if "assertion_type" in candidate_columns:
            op.drop_column("fact_extraction_candidates", "assertion_type")
