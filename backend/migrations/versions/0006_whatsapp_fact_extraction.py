"""add WhatsApp imports and reviewed fact extraction

Revision ID: 0006_whatsapp_fact_extraction
Revises: 0005_document_quality_completeness
Create Date: 2026-10-02
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0006_whatsapp_fact_extraction"
down_revision: str | None = "0005_document_quality_completeness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "conversation_imports",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("original_filename", sa.String(512)),
        sa.Column("imported_by", sa.String(255)),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("parse_status", sa.String(32), nullable=False),
        sa.Column("parse_warnings_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("case_id", "content_hash", name="uq_conversation_import_content"),
        sa.CheckConstraint("source_type IN ('whatsapp_paste', 'whatsapp_export')", name="conversation_source_type"),
        sa.CheckConstraint("parse_status IN ('parsed', 'parsed_with_warnings', 'failed')", name="conversation_parse_status"),
    )
    op.create_index("ix_conversation_imports_case_id", "conversation_imports", ["case_id"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("conversation_import_id", UUID, sa.ForeignKey("conversation_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("sender", sa.String(255)),
        sa.Column("message_timestamp", sa.DateTime(timezone=True)),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("conversation_import_id", "sequence_number", name="uq_conversation_message_sequence"),
    )
    op.create_index("ix_conversation_messages_import_id", "conversation_messages", ["conversation_import_id"])
    op.create_index("ix_conversation_messages_case_id", "conversation_messages", ["case_id"])

    op.create_table(
        "fact_extraction_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("conversation_import_id", UUID, sa.ForeignKey("conversation_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), server_default="running", nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(128)),
        sa.Column("candidate_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rejected_output_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failure_reason", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('running', 'completed', 'failed')", name="fact_extraction_run_status"),
    )
    op.create_index("ix_fact_extraction_runs_import_id", "fact_extraction_runs", ["conversation_import_id"])
    op.create_index("ix_fact_extraction_runs_created_at", "fact_extraction_runs", ["created_at"])

    op.create_table(
        "fact_extraction_candidates",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_import_id", UUID, sa.ForeignKey("conversation_imports.id", ondelete="SET NULL")),
        sa.Column("extraction_run_id", UUID, sa.ForeignKey("fact_extraction_runs.id", ondelete="SET NULL")),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value_json", JSONB, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("source_message_ids_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(128)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("conflicting_fact_id", UUID, sa.ForeignKey("facts.id", ondelete="SET NULL")),
        sa.Column("authoritative_fact_id", UUID, sa.ForeignKey("facts.id", ondelete="SET NULL")),
        sa.Column("corrected_value_json", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by", sa.String(255)),
        sa.Column("review_reason", sa.Text()),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="fact_candidate_confidence_range"),
        sa.CheckConstraint("status IN ('proposed', 'conflict', 'accepted', 'corrected', 'rejected')", name="fact_candidate_status"),
    )
    op.create_index("ix_fact_candidates_case_id", "fact_extraction_candidates", ["case_id"])
    op.create_index("ix_fact_candidates_import_id", "fact_extraction_candidates", ["conversation_import_id"])
    op.create_index("ix_fact_candidates_status", "fact_extraction_candidates", ["status"])


def downgrade() -> None:
    op.drop_table("fact_extraction_candidates")
    op.drop_table("fact_extraction_runs")
    op.drop_table("conversation_messages")
    op.drop_table("conversation_imports")
