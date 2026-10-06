"""add document quality and requirement completeness audit

Revision ID: 0005_doc_quality_completeness
Revises: 0004_document_classification
Create Date: 2026-10-02
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005_doc_quality_completeness"
down_revision: str | None = "0004_document_classification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_check_constraint(
        "document_quality_state",
        "documents",
        "quality_status IN ('not_checked', 'checking', 'passed', 'failed', "
        "'manual_review', 'manual_accepted', 'manual_rejected', 'error')",
    )
    op.add_column("requirements", sa.Column("fulfillment_source", sa.String(32)))
    op.add_column(
        "requirements", sa.Column("fulfillment_updated_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "requirements",
        sa.Column(
            "completeness_policy_json",
            JSONB,
            server_default=sa.text("'{\"mode\": \"single_document\"}'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE requirements SET fulfillment_source = CASE "
        "WHEN fulfillment_status = 'waived' THEN 'waived' "
        "WHEN fulfillment_status = 'fulfilled' THEN 'manual' ELSE NULL END"
    )
    op.create_check_constraint(
        "requirement_fulfillment_source",
        "requirements",
        "fulfillment_source IS NULL OR fulfillment_source IN "
        "('manual', 'automatic_document_evidence', 'waived')",
    )

    op.create_table(
        "document_quality_checks",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("document_id", UUID, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), server_default="checking", nullable=False),
        sa.Column("checks_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("issues_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("extracted_metadata_json", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("evaluator_version", sa.String(128)),
        sa.Column("document_hash", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by", sa.String(255)),
        sa.Column("review_decision", sa.String(16)),
        sa.Column("review_reason", sa.Text()),
        sa.CheckConstraint(
            "status IN ('checking', 'passed', 'failed', 'manual_review', 'error')",
            name="quality_check_status",
        ),
        sa.CheckConstraint(
            "review_decision IS NULL OR review_decision IN ('accepted', 'rejected')",
            name="quality_review_decision",
        ),
    )
    op.create_index("ix_document_quality_checks_document_id", "document_quality_checks", ["document_id"])
    op.create_index("ix_document_quality_checks_created_at", "document_quality_checks", ["created_at"])

    op.create_table(
        "requirement_completeness_evaluations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("requirement_id", UUID, sa.ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("matched_document_ids_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("accepted_document_ids_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("matched_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("accepted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("coverage_json", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("missing_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("trigger", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint(
            "status IN ('complete', 'incomplete', 'not_evaluable')",
            name="requirement_completeness_status",
        ),
    )
    op.create_index("ix_requirement_completeness_requirement_id", "requirement_completeness_evaluations", ["requirement_id"])
    op.create_index("ix_requirement_completeness_created_at", "requirement_completeness_evaluations", ["created_at"])

    op.create_table(
        "requirement_fulfillment_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("requirement_id", UUID, sa.ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=False),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(255)),
        sa.Column("document_ids_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint(
            "source IN ('manual', 'automatic_document_evidence', 'waived')",
            name="fulfillment_event_source",
        ),
    )
    op.create_index("ix_requirement_fulfillment_events_requirement_id", "requirement_fulfillment_events", ["requirement_id"])


def downgrade() -> None:
    op.drop_table("requirement_fulfillment_events")
    op.drop_table("requirement_completeness_evaluations")
    op.drop_table("document_quality_checks")
    op.drop_constraint("requirement_fulfillment_source", "requirements", type_="check")
    op.drop_column("requirements", "completeness_policy_json")
    op.drop_column("requirements", "fulfillment_updated_at")
    op.drop_column("requirements", "fulfillment_source")
    op.drop_constraint("document_quality_state", "documents", type_="check")
