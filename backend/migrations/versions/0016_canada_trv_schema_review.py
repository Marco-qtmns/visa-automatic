"""persist Canada TRV schema-driven review records

Revision ID: 0016_canada_trv_schema_review
Revises: 0015_intake_failure_detail
Create Date: 2026-10-11
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0016_canada_trv_schema_review"
down_revision: str | None = "0015_intake_failure_detail"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canada_trv_review_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("schema_id", sa.String(80), nullable=False),
        sa.Column("schema_version", sa.String(24), nullable=False),
        sa.Column("variant_id", sa.String(40), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("raw_source_reference", sa.String(255), nullable=False),
        sa.Column("raw_headers_json", sa.JSON(), nullable=False),
        sa.Column("imported_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "canada_trv_review_applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("import_row_number", sa.Integer(), nullable=False),
        sa.Column("raw_values_json", sa.JSON(), nullable=False),
        sa.Column("normalized_data_json", sa.JSON(), nullable=False),
        sa.Column("validation_issues_json", sa.JSON(), nullable=False),
        sa.Column("section_reviews_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("confirmed_by", sa.String(255)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["import_id"], ["canada_trv_review_imports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_id", "import_row_number", name="uq_canada_trv_review_import_row"),
    )
    op.create_index("ix_canada_trv_review_applications_import_id", "canada_trv_review_applications", ["import_id"])
    op.create_index("ix_canada_trv_review_applications_case_id", "canada_trv_review_applications", ["case_id"])
    op.create_index("ix_canada_trv_review_case_created", "canada_trv_review_applications", ["case_id", "created_at"])
    op.create_table(
        "canada_trv_review_fields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("field_id", sa.String(16), nullable=False),
        sa.Column("section_id", sa.String(64), nullable=False),
        sa.Column("target_path", sa.String(255), nullable=False),
        sa.Column("source_csv_column_1based", sa.Integer()),
        sa.Column("source_header", sa.Text(), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("normalized_value_json", sa.JSON()),
        sa.Column("edited_value_json", sa.JSON()),
        sa.Column("applicability", sa.String(24), nullable=False),
        sa.Column("review_status", sa.String(40), nullable=False),
        sa.Column("evidence", sa.String(80)),
        sa.Column("requirement_mode", sa.String(40), nullable=False),
        sa.Column("reviewer_id", sa.String(255)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["canada_trv_review_applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", "field_id", name="uq_canada_trv_review_field"),
    )
    op.create_index("ix_canada_trv_review_fields_application_id", "canada_trv_review_fields", ["application_id"])
    op.create_index("ix_canada_trv_review_field_section", "canada_trv_review_fields", ["application_id", "section_id"])
    op.create_table(
        "canada_trv_review_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("field_id", sa.Uuid(), nullable=False),
        sa.Column("old_value_json", sa.JSON()),
        sa.Column("new_value_json", sa.JSON()),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["field_id"], ["canada_trv_review_fields.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_canada_trv_review_revisions_field_id", "canada_trv_review_revisions", ["field_id"])


def downgrade() -> None:
    op.drop_table("canada_trv_review_revisions")
    op.drop_table("canada_trv_review_fields")
    op.drop_table("canada_trv_review_applications")
    op.drop_table("canada_trv_review_imports")
