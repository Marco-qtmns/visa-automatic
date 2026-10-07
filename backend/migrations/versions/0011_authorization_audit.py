"""add immutable application audit events

Revision ID: 0011_authorization_audit
Revises: 0010_auth_foundation
Create Date: 2026-10-06
"""
from collections.abc import Sequence

from alembic import op

from backend.app.database import Base
from backend.app.models import audit as _audit_models  # noqa: F401


revision: str = "0011_authorization_audit"
down_revision: str | None = "0010_auth_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.tables["application_audit_events"].create(bind=op.get_bind(), checkfirst=False)


def downgrade() -> None:
    op.drop_table("application_audit_events")
