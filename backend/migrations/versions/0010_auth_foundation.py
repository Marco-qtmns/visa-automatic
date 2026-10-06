"""add authentication users, challenges, sessions, throttles and events

Revision ID: 0010_auth_foundation
Revises: 0009_canada_preparation_runs
Create Date: 2026-10-06
"""
from collections.abc import Sequence

from alembic import op

from backend.app.database import Base
from backend.app.models import auth as _auth_models  # noqa: F401


revision: str = "0010_auth_foundation"
down_revision: str | None = "0009_canada_preparation_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    for name in (
        "auth_users",
        "auth_login_throttles",
        "auth_sessions",
        "auth_mfa_challenges",
        "auth_security_events",
    ):
        Base.metadata.tables[name].create(bind=bind, checkfirst=False)


def downgrade() -> None:
    for name in (
        "auth_security_events",
        "auth_mfa_challenges",
        "auth_sessions",
        "auth_login_throttles",
        "auth_users",
    ):
        op.drop_table(name)
