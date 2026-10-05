"""add Canada preparation runs and generated artifacts

Revision ID: 0009_canada_preparation_runs
Revises: 0008_canada_legacy_import
Create Date: 2026-10-02
"""
from collections.abc import Sequence

from alembic import op

from backend.app.database import Base
from backend.app.models import preparation as _preparation_models  # noqa: F401

revision: str = "0009_canada_preparation_runs"
down_revision: str | None = "0008_canada_legacy_import"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.tables["preparation_runs"].create(bind=op.get_bind(), checkfirst=False)
    Base.metadata.tables["preparation_artifacts"].create(bind=op.get_bind(), checkfirst=False)


def downgrade() -> None:
    op.drop_table("preparation_artifacts")
    op.drop_table("preparation_runs")
