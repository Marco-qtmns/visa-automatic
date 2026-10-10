"""store actionable structured intake failure details

Revision ID: 0015_intake_failure_detail
Revises: 0014_person_role_alignment
Create Date: 2026-10-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0015_intake_failure_detail"
down_revision: str | None = "0014_person_role_alignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("intake_submissions", "intake_processing_attempts"):
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "failure_detail_json" not in columns:
            op.add_column(table, sa.Column("failure_detail_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("intake_processing_attempts", "intake_submissions"):
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "failure_detail_json" in columns:
            op.drop_column(table, "failure_detail_json")
