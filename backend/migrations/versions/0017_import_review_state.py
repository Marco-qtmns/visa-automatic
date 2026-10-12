"""persist Canada import candidate review decisions

Revision ID: 0017_import_review_state
Revises: 0016_canada_trv_schema_review
Create Date: 2026-10-11
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0017_import_review_state"
down_revision: str | None = "0016_canada_trv_schema_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "canada_import_candidates",
        sa.Column("canonical_review_state", sa.String(24), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("canada_import_candidates", "canonical_review_state")
