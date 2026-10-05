"""create the Milestone 1 core data model

Revision ID: 0001_core_data_model
Revises:
Create Date: 2026-10-01
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_core_data_model"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("CURRENT_TIMESTAMP")


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("case_number", sa.String(64), nullable=False, unique=True),
        sa.Column("visa_type", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(128), nullable=False),
        sa.Column("workflow_state", sa.String(32), server_default="INTAKE", nullable=False),
        *timestamps(),
    )
    op.create_table(
        "persons",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("first_name", sa.String(128), nullable=False),
        sa.Column("last_name", sa.String(128), nullable=False),
        sa.Column("roles", JSONB, nullable=False),
        *timestamps(),
    )
    op.create_index("ix_persons_case_id", "persons", ["case_id"])
    op.create_table(
        "facts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", UUID, sa.ForeignKey("persons.id", ondelete="SET NULL")),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value_json", JSONB, nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("status", sa.String(32), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_facts_case_id", "facts", ["case_id"])
    op.create_index("ix_facts_case_key", "facts", ["case_id", "key"])
    op.create_table(
        "requirements",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_type", sa.String(128), nullable=False),
        sa.Column("owner_role", sa.String(32), nullable=False),
        sa.Column("owner_person_id", UUID, sa.ForeignKey("persons.id", ondelete="SET NULL")),
        sa.Column("requirement_level", sa.String(32), nullable=False),
        sa.Column("rule_id", sa.String(128)),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("is_blocking", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_requirements_case_id", "requirements", ["case_id"])
    op.create_table(
        "documents",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", UUID, sa.ForeignKey("persons.id", ondelete="SET NULL")),
        sa.Column("document_type", sa.String(128)),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("classification_status", sa.String(32), server_default="unclassified", nullable=False),
        sa.Column("quality_status", sa.String(32), server_default="not_checked", nullable=False),
        sa.Column("metadata_json", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_documents_case_id", "documents", ["case_id"])
    op.create_table(
        "tasks",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(32), server_default="open", nullable=False),
        sa.Column("priority", sa.String(32), server_default="normal", nullable=False),
        sa.Column("blocking", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("related_requirement_id", UUID, sa.ForeignKey("requirements.id", ondelete="SET NULL")),
        sa.Column("related_document_id", UUID, sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_tasks_case_id", "tasks", ["case_id"])


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("documents")
    op.drop_table("requirements")
    op.drop_table("facts")
    op.drop_table("persons")
    op.drop_table("cases")
