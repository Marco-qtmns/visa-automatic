"""add auditable document classification suggestions

Revision ID: 0004_document_classification
Revises: 0003_document_matching
Create Date: 2026-10-02
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004_document_classification"
down_revision: str | None = "0003_document_matching"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_check_constraint(
        "document_classification_state",
        "documents",
        "classification_status IN ('unclassified', 'classification_pending', "
        "'suggestion_available', 'confirmed', 'classification_failed')",
    )
    op.create_table(
        "document_classifications",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "document_id",
            UUID,
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("suggested_document_type", sa.String(128)),
        sa.Column(
            "suggested_person_id",
            UUID,
            sa.ForeignKey("persons.id", ondelete="SET NULL"),
        ),
        sa.Column("extracted_owner_name", sa.String(255)),
        sa.Column("confidence", sa.Float()),
        sa.Column("evidence_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(128)),
        sa.Column("document_hash", sa.String(64)),
        sa.Column("raw_result_json", JSONB),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("failure_reason", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by", sa.String(255)),
        sa.Column("corrected_document_type", sa.String(128)),
        sa.Column(
            "corrected_person_id",
            UUID,
            sa.ForeignKey("persons.id", ondelete="SET NULL"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'suggested', 'accepted', 'corrected', 'rejected', 'failed')",
            name="classification_review_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="classification_confidence_range",
        ),
    )
    op.create_index(
        "ix_document_classifications_document_id",
        "document_classifications",
        ["document_id"],
    )
    op.create_index(
        "ix_document_classifications_created_at",
        "document_classifications",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("document_classifications")
    op.drop_constraint("document_classification_state", "documents", type_="check")
