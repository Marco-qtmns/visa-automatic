"""persist Canada import candidate canonical review state

Revision ID: 0016_import_review_state
Revises: 0015_intake_failure_detail
Create Date: 2026-10-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0016_import_review_state"
down_revision: str | None = "0015_intake_failure_detail"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("canada_import_candidates"):
        return
    columns = {column["name"] for column in inspector.get_columns("canada_import_candidates")}
    if "canonical_review_state" not in columns:
        op.add_column(
            "canada_import_candidates",
            sa.Column("canonical_review_state", sa.String(length=24), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("canada_import_candidates"):
        return
    columns = {column["name"] for column in inspector.get_columns("canada_import_candidates")}
    if "canonical_review_state" in columns:
        op.drop_column("canada_import_candidates", "canonical_review_state")
