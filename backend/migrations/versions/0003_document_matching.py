"""add manual requirement-document matches

Revision ID: 0003_document_matching
Revises: 0002_workflow_state_machine
Create Date: 2026-10-02
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_document_matching"
down_revision: str | None = "0002_workflow_state_machine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "requirement_document_matches",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "requirement_id",
            UUID,
            sa.ForeignKey("requirements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            UUID,
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(255)),
        sa.Column("note", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.UniqueConstraint(
            "requirement_id", "document_id", name="uq_requirement_document_match"
        ),
    )
    op.create_index(
        "ix_requirement_document_matches_requirement_id",
        "requirement_document_matches",
        ["requirement_id"],
    )
    op.create_index(
        "ix_requirement_document_matches_document_id",
        "requirement_document_matches",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_table("requirement_document_matches")
