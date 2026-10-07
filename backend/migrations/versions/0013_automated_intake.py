"""add automated intake submissions and processing attempts

Revision ID: 0013_automated_intake
Revises: 0012_import_raw_provenance
Create Date: 2026-10-07
"""
from collections.abc import Sequence

from alembic import op

from backend.app.database import Base
from backend.app.models import intake as _intake_models  # noqa: F401


revision: str = "0013_automated_intake"
down_revision: str | None = "0012_import_raw_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in ("intake_submissions", "intake_processing_attempts"):
        Base.metadata.tables[name].create(bind=op.get_bind(), checkfirst=False)


def downgrade() -> None:
    for name in ("intake_processing_attempts", "intake_submissions"):
        op.drop_table(name)
