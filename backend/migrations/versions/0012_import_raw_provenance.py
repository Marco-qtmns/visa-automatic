"""preserve raw value for Canada import provenance

Revision ID: 0012_import_raw_provenance
Revises: 0011_authorization_audit
Create Date: 2026-10-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.app.models.core import JSON_TYPE


revision: str = "0012_import_raw_provenance"
down_revision: str | None = "0011_authorization_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "canada_import_candidates",
        sa.Column("raw_value_json", JSON_TYPE, nullable=True),
    )
    op.execute(
        "UPDATE canada_import_candidates "
        "SET raw_value_json = proposed_value_json WHERE raw_value_json IS NULL"
    )
    with op.batch_alter_table("canada_import_candidates") as batch_op:
        batch_op.alter_column("raw_value_json", nullable=False)


def downgrade() -> None:
    op.drop_column("canada_import_candidates", "raw_value_json")
