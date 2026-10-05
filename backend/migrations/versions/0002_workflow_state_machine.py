"""add controlled workflow state and transition audit

Revision ID: 0002_workflow_state_machine
Revises: 0001_core_data_model
Create Date: 2026-10-01
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002_workflow_state_machine"
down_revision: str | None = "0001_core_data_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("CURRENT_TIMESTAMP")
WORKFLOW_VALUES = "'INTAKE', 'DOCUMENTS', 'PREPARE', 'REVIEW', 'READY', 'SUBMITTED'"


def upgrade() -> None:
    op.create_check_constraint(
        "workflow_state",
        "cases",
        f"workflow_state IN ({WORKFLOW_VALUES})",
    )
    op.add_column(
        "requirements",
        sa.Column(
            "fulfillment_status",
            sa.String(16),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column("requirements", sa.Column("waiver_reason", sa.Text()))
    op.add_column("requirements", sa.Column("waived_by", sa.String(255)))
    op.add_column(
        "requirements", sa.Column("waived_at", sa.DateTime(timezone=True))
    )
    op.create_check_constraint(
        "requirement_fulfillment_status",
        "requirements",
        "fulfillment_status IN ('pending', 'fulfilled', 'waived')",
    )
    op.create_table(
        "workflow_transitions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "case_id",
            UUID,
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_state", sa.String(32), nullable=False),
        sa.Column("to_state", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(255)),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.CheckConstraint(
            f"from_state IN ({WORKFLOW_VALUES})",
            name="workflow_transition_from_state",
        ),
        sa.CheckConstraint(
            f"to_state IN ({WORKFLOW_VALUES})",
            name="workflow_transition_to_state",
        ),
    )
    op.create_index(
        "ix_workflow_transitions_case_id", "workflow_transitions", ["case_id"]
    )


def downgrade() -> None:
    op.drop_table("workflow_transitions")
    op.drop_constraint(
        "requirement_fulfillment_status", "requirements", type_="check"
    )
    op.drop_column("requirements", "waived_at")
    op.drop_column("requirements", "waived_by")
    op.drop_column("requirements", "waiver_reason")
    op.drop_column("requirements", "fulfillment_status")
    op.drop_constraint("workflow_state", "cases", type_="check")
