"""add canonical Canada application model

Revision ID: 0007_canada_application_model
Revises: 0006_whatsapp_fact_extraction
Create Date: 2026-10-02

The table list is intentionally frozen here. SQLAlchemy copies each declaration before
DDL execution so the live application metadata is not mutated during migration.
"""
from collections.abc import Sequence

from alembic import op

from backend.app.database import Base
from backend.app.models import canada as _canada_models  # noqa: F401


revision: str = "0007_canada_application_model"
down_revision: str | None = "0006_whatsapp_fact_extraction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLES = [
    "canada_applications",
    "case_person_roles",
    "person_biographies",
    "person_citizenships",
    "person_identifiers",
    "contact_points",
    "applicant_residences",
    "travel_documents",
    "trip_plans",
    "canada_organizations",
    "funding_sources",
    "canada_addresses",
    "host_records",
    "family_relationships",
    "education_records",
    "activity_records",
    "residence_history_records",
    "travel_history_records",
    "official_application_answers",
    "official_explanations",
    "representative_profiles",
    "representative_profile_revisions",
    "representative_authorizations",
    "field_provenance_reviews",
]


def upgrade() -> None:
    # Create each frozen table in dependency order. The declarations retain every
    # FK, unique/check constraint, and partial index on PostgreSQL and SQLite.
    for name in TABLES:
        Base.metadata.tables[name].create(bind=op.get_bind(), checkfirst=False)


def downgrade() -> None:
    for name in reversed(TABLES):
        op.drop_table(name)
