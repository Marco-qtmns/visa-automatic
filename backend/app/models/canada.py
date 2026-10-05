from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint, Uuid, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .core import JSON_TYPE, utcnow


REVIEW_VALUES = "'unreviewed', 'confirmed', 'corrected', 'needs_review', 'rejected'"


class OperationalRole(StrEnum):
    APPLICANT = "applicant"
    REPRESENTATIVE = "representative"
    SPONSOR = "sponsor"
    HOST = "host"
    OTHER = "other"


class FamilyRelationshipType(StrEnum):
    SPOUSE = "spouse"
    FORMER_SPOUSE = "former_spouse"
    PARENT = "parent"
    CHILD = "child"


class ReviewState(StrEnum):
    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class OfficialAnswerValue(StrEnum):
    YES = "yes"
    NO = "no"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class HostType(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"


class AddressContext(StrEnum):
    RESIDENTIAL = "residential"
    MAILING = "mailing"
    HOST = "host"
    FAMILY_MEMBER = "family_member"


class ProvenanceEntityType(StrEnum):
    PERSON = "person"
    APPLICATION = "application"
    PERSON_BIOGRAPHY = "person_biography"
    ADDRESS = "address"
    RESIDENCE = "residence"
    TRAVEL_DOCUMENT = "travel_document"
    TRIP_PLAN = "trip_plan"
    FUNDING_SOURCE = "funding_source"
    HOST = "host"
    FAMILY_RELATIONSHIP = "family_relationship"
    EDUCATION = "education"
    ACTIVITY = "activity"
    RESIDENCE_HISTORY = "residence_history"
    TRAVEL_HISTORY = "travel_history"
    OFFICIAL_ANSWER = "official_answer"
    OFFICIAL_EXPLANATION = "official_explanation"
    REPRESENTATIVE_AUTHORIZATION = "representative_authorization"


class CanadaApplication(Base):
    __tablename__ = "canada_applications"
    __table_args__ = (CheckConstraint(
        f"application_date_review_state IN ({REVIEW_VALUES})",
        name="canada_application_date_review_state_valid",
    ),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), unique=True, nullable=False)
    applicant_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="RESTRICT"), unique=True)
    legal_guardian_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="RESTRICT"))
    official_application_date: Mapped[date | None] = mapped_column(Date)
    application_date_review_state: Mapped[str] = mapped_column(String(24), default=ReviewState.UNREVIEWED, nullable=False)
    native_language_code: Mapped[str | None] = mapped_column(String(32))
    preferred_language_code: Mapped[str | None] = mapped_column(String(32))
    service_language_code: Mapped[str | None] = mapped_column(String(32))
    mailing_same_as_residential: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class CasePersonRole(Base):
    __tablename__ = "case_person_roles"
    __table_args__ = (
        UniqueConstraint("case_id", "person_id", "role", name="uq_case_person_operational_role"),
        CheckConstraint("role IN ('applicant', 'representative', 'sponsor', 'host', 'other')", name="case_person_role_valid"),
        Index("uq_case_one_applicant_role", "case_id", unique=True,
              postgresql_where=text("role = 'applicant'"), sqlite_where=text("role = 'applicant'")),
        Index("uq_case_one_representative_role", "case_id", unique=True,
              postgresql_where=text("role = 'representative'"), sqlite_where=text("role = 'representative'")),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    assigned_by: Mapped[str | None] = mapped_column(String(255))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PersonBiography(Base):
    __tablename__ = "person_biographies"
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), primary_key=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    other_names: Mapped[str | None] = mapped_column(String(255))
    sex: Mapped[str | None] = mapped_column(String(32))
    birth_city: Mapped[str | None] = mapped_column(String(128))
    birth_state_province: Mapped[str | None] = mapped_column(String(128))
    birth_country_code: Mapped[str | None] = mapped_column(String(3))
    marital_status: Mapped[str | None] = mapped_column(String(32))
    occupation_text: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class PersonCitizenship(Base):
    __tablename__ = "person_citizenships"
    __table_args__ = (
        UniqueConstraint("person_id", "country_code", name="uq_person_citizenship"),
        Index("uq_person_primary_citizenship", "person_id", unique=True,
              postgresql_where=text("is_primary"), sqlite_where=text("is_primary = 1")),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True)
    country_code: Mapped[str] = mapped_column(String(3), nullable=False)
    citizenship_type: Mapped[str] = mapped_column(String(32), default="citizen", nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PersonIdentifier(Base):
    __tablename__ = "person_identifiers"
    __table_args__ = (
        UniqueConstraint("person_id", "country_code", "identifier_type", name="uq_person_identifier"),
        CheckConstraint("expiry_date IS NULL OR issue_date IS NULL OR expiry_date >= issue_date", name="person_identifier_date_order"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True)
    country_code: Mapped[str] = mapped_column(String(3), nullable=False)
    identifier_type: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(128), nullable=False)
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)


class ContactPoint(Base):
    __tablename__ = "contact_points"
    __table_args__ = (
        UniqueConstraint("person_id", "type", "purpose", "sort_order", name="uq_person_contact_order"),
        CheckConstraint("type IN ('email', 'phone')", name="contact_point_type_valid"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(8))
    purpose: Mapped[str] = mapped_column(String(32), default="primary", nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Address(Base):
    __tablename__ = "canada_addresses"
    __table_args__ = (
        UniqueConstraint("application_id", "context", "owner_id", name="uq_canada_address_owner_context"),
        CheckConstraint("context IN ('residential', 'mailing', 'host', 'family_member')", name="canada_address_context_valid"),
        CheckConstraint(f"review_state IN ({REVIEW_VALUES})", name="canada_address_review_state_valid"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    context: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    po_box: Mapped[str | None] = mapped_column(String(64))
    unit: Mapped[str | None] = mapped_column(String(64))
    street_number: Mapped[str | None] = mapped_column(String(64))
    street_name: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(128))
    state_province: Mapped[str | None] = mapped_column(String(128))
    postal_code: Mapped[str | None] = mapped_column(String(32))
    country_code: Mapped[str | None] = mapped_column(String(3))
    unstructured_source_text: Mapped[str | None] = mapped_column(Text)
    review_state: Mapped[str] = mapped_column(String(24), default=ReviewState.UNREVIEWED, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class ApplicantResidence(Base):
    __tablename__ = "applicant_residences"
    __table_args__ = (
        Index("uq_application_current_residence", "application_id", unique=True,
              postgresql_where=text("is_current"), sqlite_where=text("is_current = 1")),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    country_code: Mapped[str] = mapped_column(String(3), nullable=False)
    immigration_status_code: Mapped[str | None] = mapped_column(String(64))
    resident_since: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class TravelDocument(Base):
    __tablename__ = "travel_documents"
    __table_args__ = (
        UniqueConstraint("application_id", "sort_order", name="uq_travel_document_order"),
        Index("uq_application_primary_passport", "application_id", unique=True,
              postgresql_where=text("is_primary"), sqlite_where=text("is_primary = 1")),
        CheckConstraint("expiry_date IS NULL OR issue_date IS NULL OR expiry_date >= issue_date", name="travel_document_date_order"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="RESTRICT"), nullable=False)
    document_type: Mapped[str] = mapped_column(String(32), default="passport", nullable=False)
    number: Mapped[str] = mapped_column(String(128), nullable=False)
    issuing_country_code: Mapped[str] = mapped_column(String(3), nullable=False)
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    details: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class TripPlan(Base):
    __tablename__ = "trip_plans"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_applications.id", ondelete="CASCADE"), unique=True, nullable=False)
    intake_purpose_text: Mapped[str | None] = mapped_column(Text)
    imm5257_purpose_code: Mapped[str | None] = mapped_column(String(64))
    purpose_review_state: Mapped[str] = mapped_column(String(24), default=ReviewState.UNREVIEWED, nullable=False)
    arrival_date: Mapped[date | None] = mapped_column(Date)
    departure_date: Mapped[date | None] = mapped_column(Date)
    available_funds_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    available_funds_currency: Mapped[str | None] = mapped_column(String(3))
    funds_source_reference: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("departure_date IS NULL OR arrival_date IS NULL OR departure_date >= arrival_date", name="trip_date_order"),
        CheckConstraint(f"purpose_review_state IN ({REVIEW_VALUES})", name="trip_purpose_review_state_valid"),
    )


class Organization(Base):
    __tablename__ = "canada_organizations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_type: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))


class FundingSource(Base):
    __tablename__ = "funding_sources"
    __table_args__ = (UniqueConstraint("trip_plan_id", "sort_order", name="uq_funding_source_order"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    trip_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trip_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    payer_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canada_organizations.id", ondelete="SET NULL"))
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class HostRecord(Base):
    __tablename__ = "host_records"
    __table_args__ = (
        UniqueConstraint("trip_plan_id", "sort_order", name="uq_host_order"),
        CheckConstraint("host_type IN ('person', 'organization')", name="host_type_valid"),
        CheckConstraint("(host_type = 'person' AND person_id IS NOT NULL AND organization_id IS NULL) OR (host_type = 'organization' AND organization_id IS NOT NULL AND person_id IS NULL)", name="host_party_xor"),
        Index("uq_trip_primary_host", "trip_plan_id", unique=True,
              postgresql_where=text("is_primary"), sqlite_where=text("is_primary = 1")),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    trip_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trip_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    host_type: Mapped[str] = mapped_column(String(24), nullable=False)
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="RESTRICT"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canada_organizations.id", ondelete="RESTRICT"))
    relationship_to_applicant: Mapped[str | None] = mapped_column(String(128))
    family_relationship: Mapped[str | None] = mapped_column(String(128))
    immigration_status_in_canada: Mapped[str | None] = mapped_column(String(128))
    address_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canada_addresses.id", ondelete="SET NULL"), unique=True)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class FamilyRelationship(Base):
    __tablename__ = "family_relationships"
    __table_args__ = (
        UniqueConstraint("application_id", "relationship_type", "sort_order", name="uq_family_relationship_order"),
        UniqueConstraint("application_id", "related_person_id", "relationship_type", name="uq_family_relationship_person_type"),
        CheckConstraint("relationship_type IN ('spouse', 'former_spouse', 'parent', 'child')", name="family_relationship_type_valid"),
        CheckConstraint("applicant_person_id <> related_person_id", name="family_relationship_people_differ"),
        CheckConstraint("relationship_end_date IS NULL OR relationship_start_date IS NULL OR relationship_end_date >= relationship_start_date", name="family_relationship_date_order"),
        Index("uq_application_current_spouse", "application_id", unique=True,
              postgresql_where=text("relationship_type = 'spouse' AND is_current"),
              sqlite_where=text("relationship_type = 'spouse' AND is_current = 1")),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    applicant_person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="RESTRICT"), nullable=False)
    related_person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="RESTRICT"), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_type: Mapped[str | None] = mapped_column(String(32))
    guardian_status: Mapped[str | None] = mapped_column(String(64))
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    relationship_start_date: Mapped[date | None] = mapped_column(Date)
    relationship_end_date: Mapped[date | None] = mapped_column(Date)
    previous_relationship_type: Mapped[str | None] = mapped_column(String(64))
    accompanying_applicant: Mapped[bool | None] = mapped_column(Boolean)
    residence_same_as_applicant: Mapped[bool | None] = mapped_column(Boolean)
    death_details: Mapped[str | None] = mapped_column(Text)
    address_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canada_addresses.id", ondelete="SET NULL"), unique=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class EducationRecord(Base):
    __tablename__ = "education_records"
    __table_args__ = (
        UniqueConstraint("application_id", "sort_order", name="uq_education_order"),
        Index("uq_application_person_primary_education", "application_id", "person_id", unique=True,
              postgresql_where=text("is_primary"), sqlite_where=text("is_primary = 1")),
        CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="education_date_order"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="RESTRICT"), nullable=False)
    level: Mapped[str | None] = mapped_column(String(128))
    institution_name: Mapped[str | None] = mapped_column(String(255))
    course: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    city: Mapped[str | None] = mapped_column(String(128))
    state_province: Mapped[str | None] = mapped_column(String(128))
    country_code: Mapped[str | None] = mapped_column(String(3))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class ActivityRecord(Base):
    __tablename__ = "activity_records"
    __table_args__ = (
        UniqueConstraint("application_id", "sort_order", name="uq_activity_order"),
        Index("uq_application_person_current_activity", "application_id", "person_id", unique=True,
              postgresql_where=text("period_status = 'current'"), sqlite_where=text("period_status = 'current'")),
        CheckConstraint("period_status IN ('current', 'completed', 'unknown')", name="activity_period_status_valid"),
        CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="activity_date_order"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="RESTRICT"), nullable=False)
    activity_type: Mapped[str | None] = mapped_column(String(64))
    position: Mapped[str | None] = mapped_column(String(255))
    organization_name: Mapped[str | None] = mapped_column(String(255))
    duties: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    period_status: Mapped[str] = mapped_column(String(24), default="unknown", nullable=False)
    city: Mapped[str | None] = mapped_column(String(128))
    state_province: Mapped[str | None] = mapped_column(String(128))
    country_code: Mapped[str | None] = mapped_column(String(3))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class ResidenceHistoryRecord(Base):
    __tablename__ = "residence_history_records"
    __table_args__ = (
        UniqueConstraint("application_id", "sort_order", name="uq_residence_history_order"),
        CheckConstraint("end_date >= start_date", name="residence_history_date_order"),
        CheckConstraint(f"review_state IN ({REVIEW_VALUES})", name="residence_history_review_state_valid"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="RESTRICT"), nullable=False)
    country_code: Mapped[str] = mapped_column(String(3), nullable=False)
    status_or_purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    review_state: Mapped[str] = mapped_column(String(24), default=ReviewState.UNREVIEWED, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class TravelHistoryRecord(Base):
    __tablename__ = "travel_history_records"
    __table_args__ = (
        UniqueConstraint("application_id", "sort_order", name="uq_travel_history_order"),
        CheckConstraint("exit_date >= entry_date", name="travel_history_date_order"),
        CheckConstraint(f"review_state IN ({REVIEW_VALUES})", name="travel_history_review_state_valid"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="RESTRICT"), nullable=False)
    country_code: Mapped[str] = mapped_column(String(3), nullable=False)
    purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    exit_date: Mapped[date] = mapped_column(Date, nullable=False)
    review_state: Mapped[str] = mapped_column(String(24), default=ReviewState.UNREVIEWED, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class OfficialApplicationAnswer(Base):
    __tablename__ = "official_application_answers"
    __table_args__ = (
        UniqueConstraint("application_id", "question_code", name="uq_official_answer_question"),
        CheckConstraint("answer IN ('yes', 'no', 'not_applicable', 'unknown')", name="official_answer_value_valid"),
        CheckConstraint(f"review_state IN ({REVIEW_VALUES})", name="official_answer_review_state_valid"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    question_code: Mapped[str] = mapped_column(String(128), nullable=False)
    answer: Mapped[str] = mapped_column(String(24), default=OfficialAnswerValue.UNKNOWN, nullable=False)
    review_state: Mapped[str] = mapped_column(String(24), default=ReviewState.UNREVIEWED, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_reference: Mapped[str | None] = mapped_column(Text)


class OfficialExplanation(Base):
    __tablename__ = "official_explanations"
    __table_args__ = (
        UniqueConstraint("application_id", "section_code", name="uq_official_explanation_section"),
        CheckConstraint(f"review_state IN ({REVIEW_VALUES})", name="official_explanation_review_state_valid"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    section_code: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    review_state: Mapped[str] = mapped_column(String(24), default=ReviewState.UNREVIEWED, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RepresentativeProfile(Base):
    __tablename__ = "representative_profiles"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    profile_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RepresentativeProfileRevision(Base):
    __tablename__ = "representative_profile_revisions"
    __table_args__ = (UniqueConstraint("profile_id", "revision_number", name="uq_representative_profile_revision"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("representative_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    family_name: Mapped[str] = mapped_column(String(128), nullable=False)
    given_names: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_name: Mapped[str | None] = mapped_column(String(255))
    unit: Mapped[str | None] = mapped_column(String(64))
    street_number: Mapped[str | None] = mapped_column(String(64))
    street_name: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(128))
    province: Mapped[str | None] = mapped_column(String(128))
    country_code: Mapped[str | None] = mapped_column(String(3))
    postal_code: Mapped[str | None] = mapped_column(String(32))
    phone_country_code: Mapped[str | None] = mapped_column(String(8))
    phone_number: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(128))
    membership_number: Mapped[str | None] = mapped_column(String(128))
    membership_province: Mapped[str | None] = mapped_column(String(128))
    other_category_details: Mapped[str | None] = mapped_column(Text)
    supervising_lawyer: Mapped[str | None] = mapped_column(String(255))
    supervising_lawyer_membership: Mapped[str | None] = mapped_column(String(128))
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RepresentativeAuthorization(Base):
    __tablename__ = "representative_authorizations"
    __table_args__ = (CheckConstraint(
        f"review_state IN ({REVIEW_VALUES})", name="representative_authorization_review_state_valid"
    ),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_applications.id", ondelete="CASCADE"), unique=True, nullable=False)
    representative_person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="RESTRICT"), nullable=False)
    profile_revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("representative_profile_revisions.id", ondelete="RESTRICT"), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    cancelled_representative_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    cancelled_organization_name: Mapped[str | None] = mapped_column(String(255))
    review_state: Mapped[str] = mapped_column(String(24), default=ReviewState.UNREVIEWED, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FieldProvenanceReview(Base):
    __tablename__ = "field_provenance_reviews"
    __table_args__ = (
        Index("ix_field_provenance_subject", "entity_type", "entity_id", "field_key"),
        CheckConstraint("entity_type IN ('person', 'application', 'person_biography', 'address', 'residence', 'travel_document', 'trip_plan', 'funding_source', 'host', 'family_relationship', 'education', 'activity', 'residence_history', 'travel_history', 'official_answer', 'official_explanation', 'representative_authorization')", name="field_provenance_entity_type_valid"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="field_provenance_confidence_range"),
        CheckConstraint(f"review_state IN ({REVIEW_VALUES})", name="field_provenance_review_state_valid"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    field_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)
    source_digest: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    review_state: Mapped[str] = mapped_column(String(24), default=ReviewState.UNREVIEWED, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CanadaLegacyImportRun(Base):
    __tablename__ = "canada_legacy_import_runs"
    __table_args__ = (
        UniqueConstraint("case_id", "source_type", "source_hash", "mapping_version", name="uq_canada_import_source"),
        CheckConstraint("source_type IN ('google_verified_csv', 'canada_case_json', 'representative_profile_json')", name="canada_import_source_type_valid"),
        CheckConstraint("status IN ('previewed', 'reviewing', 'applied', 'failed')", name="canada_import_status_valid"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="previewed", nullable=False)
    imported_by: Mapped[str | None] = mapped_column(String(255))
    counts_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    warnings_json: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CanadaImportCandidate(Base):
    __tablename__ = "canada_import_candidates"
    __table_args__ = (
        UniqueConstraint("import_run_id", "source_path", "source_record_key", "target_entity_type", "target_field", name="uq_canada_import_candidate"),
        CheckConstraint("status IN ('new', 'same', 'conflict', 'ambiguous', 'accepted', 'rejected', 'applied')", name="canada_import_candidate_status_valid"),
        CheckConstraint("source_classification IN ('applicant_direct', 'legacy_staff_review', 'legacy_derived', 'representative_profile', 'legacy_narrative_derived')", name="canada_import_source_class_valid"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    import_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_legacy_import_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    domain_section: Mapped[str] = mapped_column(String(40), nullable=False)
    employee_label: Mapped[str] = mapped_column(String(255), nullable=False)
    target_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    target_field: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), default="set_field", nullable=False)
    source_path: Mapped[str] = mapped_column(String(255), nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(255), default="scalar", nullable=False)
    source_classification: Mapped[str] = mapped_column(String(40), nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_value_json: Mapped[Any] = mapped_column(JSON_TYPE, nullable=False)
    current_value_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    conflict_type: Mapped[str | None] = mapped_column(String(64))
    review_policy: Mapped[str] = mapped_column(String(40), nullable=False)
    conflict_policy: Mapped[str] = mapped_column(String(40), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class LegacyImportEntityLink(Base):
    __tablename__ = "legacy_import_entity_links"
    __table_args__ = (
        UniqueConstraint("case_id", "source_type", "source_record_key", "canonical_entity_type", name="uq_legacy_import_entity_link"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    first_import_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_legacy_import_runs.id", ondelete="RESTRICT"), nullable=False)
    last_import_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canada_legacy_import_runs.id", ondelete="RESTRICT"), nullable=False)
    employee_order_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
