"""add controlled Canada legacy import audit

Revision ID: 0008_canada_legacy_import
Revises: 0007_canada_application_model
Create Date: 2026-10-02
"""
from collections.abc import Sequence

from alembic import op

from backend.app.database import Base
from backend.app.models import canada as _canada_models  # noqa: F401

revision: str = "0008_canada_legacy_import"
down_revision: str | None = "0007_canada_application_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ["canada_legacy_import_runs", "canada_import_candidates", "legacy_import_entity_links"]


def upgrade() -> None:
    op.drop_constraint("field_provenance_entity_type_valid", "field_provenance_reviews", type_="check")
    op.create_check_constraint(
        "field_provenance_entity_type_valid", "field_provenance_reviews",
        "entity_type IN ('person', 'application', 'person_biography', 'address', 'residence', 'travel_document', 'trip_plan', 'funding_source', 'host', 'family_relationship', 'education', 'activity', 'residence_history', 'travel_history', 'official_answer', 'official_explanation', 'representative_authorization')",
    )
    for name in TABLES:
        Base.metadata.tables[name].create(bind=op.get_bind(), checkfirst=False)


def downgrade() -> None:
    for name in reversed(TABLES):
        op.drop_table(name)
    op.drop_constraint("field_provenance_entity_type_valid", "field_provenance_reviews", type_="check")
    op.create_check_constraint(
        "field_provenance_entity_type_valid", "field_provenance_reviews",
        "entity_type IN ('application', 'person_biography', 'address', 'residence', 'travel_document', 'trip_plan', 'funding_source', 'host', 'family_relationship', 'education', 'activity', 'residence_history', 'travel_history', 'official_answer', 'official_explanation', 'representative_authorization')",
    )
