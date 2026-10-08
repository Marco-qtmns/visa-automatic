from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models.canada import (
    AddressContext, FamilyRelationshipType, HostType, OfficialAnswerValue,
    OperationalRole, ProvenanceEntityType, ReviewState,
)


class ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CanadaApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    applicant_person_id: uuid.UUID


class CanadaApplicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    official_application_date: date | None = None
    legal_guardian_person_id: uuid.UUID | None = None
    application_date_review_state: ReviewState | None = None
    native_language_code: str | None = Field(default=None, max_length=32)
    preferred_language_code: str | None = Field(default=None, max_length=32)
    service_language_code: str | None = Field(default=None, max_length=32)
    mailing_same_as_residential: bool | None = None


class CanadaApplicationRead(ReadModel):
    id: uuid.UUID
    case_id: uuid.UUID
    applicant_person_id: uuid.UUID | None
    legal_guardian_person_id: uuid.UUID | None
    official_application_date: date | None
    application_date_review_state: str
    native_language_code: str | None
    preferred_language_code: str | None
    service_language_code: str | None
    mailing_same_as_residential: bool | None
    created_at: datetime
    updated_at: datetime


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person_id: uuid.UUID
    role: OperationalRole
    assigned_by: str | None = Field(default=None, max_length=255)


class RoleRead(ReadModel):
    id: uuid.UUID
    case_id: uuid.UUID
    person_id: uuid.UUID
    role: str
    assigned_by: str | None
    assigned_at: datetime


class BiographyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date_of_birth: date | None = None
    other_names: str | None = Field(default=None, max_length=255)
    sex: str | None = Field(default=None, max_length=32)
    birth_city: str | None = Field(default=None, max_length=128)
    birth_state_province: str | None = Field(default=None, max_length=128)
    birth_country_code: str | None = Field(default=None, min_length=2, max_length=3)
    marital_status: str | None = Field(default=None, max_length=32)
    occupation_text: str | None = Field(default=None, max_length=255)


class BiographyRead(BiographyWrite, ReadModel):
    person_id: uuid.UUID
    updated_at: datetime


class CitizenshipCreate(BaseModel):
    person_id: uuid.UUID
    country_code: str = Field(min_length=2, max_length=3)
    citizenship_type: str = Field(default="citizen", max_length=32)
    is_primary: bool = False
    sort_order: int = Field(ge=0)


class IdentifierCreate(BaseModel):
    person_id: uuid.UUID
    country_code: str = Field(min_length=2, max_length=3)
    identifier_type: str = Field(min_length=1, max_length=32)
    value: str = Field(min_length=1, max_length=128)
    issue_date: date | None = None
    expiry_date: date | None = None


class ContactPointCreate(BaseModel):
    person_id: uuid.UUID
    type: Literal["email", "phone"]
    value: str = Field(min_length=1, max_length=255)
    country_code: str | None = Field(default=None, max_length=8)
    purpose: str = Field(default="primary", max_length=32)
    is_primary: bool = False
    sort_order: int = Field(ge=0)


class AddressWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: AddressContext
    owner_id: uuid.UUID
    po_box: str | None = None
    unit: str | None = None
    street_number: str | None = None
    street_name: str | None = None
    city: str | None = None
    state_province: str | None = None
    postal_code: str | None = None
    country_code: str | None = Field(default=None, max_length=3)
    unstructured_source_text: str | None = None
    review_state: ReviewState = ReviewState.UNREVIEWED


class AddressPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    po_box: str | None = None
    unit: str | None = None
    street_number: str | None = None
    street_name: str | None = None
    city: str | None = None
    state_province: str | None = None
    postal_code: str | None = None
    country_code: str | None = Field(default=None, max_length=3)
    unstructured_source_text: str | None = None
    review_state: ReviewState | None = None


class ApplicantResidenceCreate(BaseModel):
    country_code: str = Field(min_length=2, max_length=3)
    immigration_status_code: str | None = None
    resident_since: date | None = None
    is_current: bool = True


class TravelDocumentCreate(BaseModel):
    person_id: uuid.UUID
    document_type: str = "passport"
    number: str = Field(min_length=1, max_length=128)
    issuing_country_code: str = Field(min_length=2, max_length=3)
    issue_date: date | None = None
    expiry_date: date | None = None
    details: str | None = None
    is_primary: bool = False
    sort_order: int = Field(ge=0)


class TripPlanWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intake_purpose_text: str | None = None
    imm5257_purpose_code: str | None = None
    purpose_review_state: ReviewState = ReviewState.UNREVIEWED
    arrival_date: date | None = None
    departure_date: date | None = None
    available_funds_amount: float | None = Field(default=None, ge=0)
    available_funds_currency: str | None = Field(default=None, max_length=3)
    funds_source_reference: str | None = None


class OrganizationCreate(BaseModel):
    legal_name: str = Field(min_length=1, max_length=255)
    organization_type: str | None = None
    email: str | None = None
    phone: str | None = None


class FundingSourceCreate(BaseModel):
    payer_kind: str = Field(min_length=1, max_length=32)
    person_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    description: str | None = None
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    is_primary: bool = False
    sort_order: int = Field(ge=0)


class HostCreate(BaseModel):
    host_type: HostType
    person_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    relationship_to_applicant: str | None = None
    family_relationship: str | None = None
    immigration_status_in_canada: str | None = None
    email: str | None = None
    phone: str | None = None
    is_primary: bool = False
    sort_order: int = Field(ge=0)

    @model_validator(mode="after")
    def party_matches_type(self):
        if self.host_type == HostType.PERSON and (self.person_id is None or self.organization_id is not None):
            raise ValueError("person host requires only person_id")
        if self.host_type == HostType.ORGANIZATION and (self.organization_id is None or self.person_id is not None):
            raise ValueError("organization host requires only organization_id")
        return self


class FamilyRelationshipCreate(BaseModel):
    related_person_id: uuid.UUID
    relationship_type: FamilyRelationshipType
    parent_type: str | None = None
    guardian_status: str | None = None
    is_current: bool = False
    relationship_start_date: date | None = None
    relationship_end_date: date | None = None
    previous_relationship_type: str | None = None
    accompanying_applicant: bool | None = None
    residence_same_as_applicant: bool | None = None
    death_details: str | None = None
    sort_order: int = Field(ge=0)

    @model_validator(mode="after")
    def relationship_semantics_are_consistent(self):
        if self.relationship_type == FamilyRelationshipType.PARENT:
            if self.parent_type not in {None, "mother", "father"}:
                raise ValueError("parent_type must be mother or father")
        elif self.parent_type is not None:
            raise ValueError("parent_type is only valid for a parent relationship")
        expected_current = self.relationship_type == FamilyRelationshipType.SPOUSE
        if self.is_current != expected_current:
            raise ValueError(
                "is_current identifies the current spouse; all other family relationship types must be false"
            )
        return self


class EducationCreate(BaseModel):
    person_id: uuid.UUID
    level: str | None = None
    institution_name: str | None = None
    course: str | None = None
    details: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    city: str | None = None
    state_province: str | None = None
    country_code: str | None = None
    is_primary: bool = False
    sort_order: int = Field(ge=0)


class ActivityCreate(BaseModel):
    person_id: uuid.UUID
    activity_type: str | None = None
    position: str | None = None
    organization_name: str | None = None
    duties: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    period_status: Literal["current", "completed", "unknown"] = "unknown"
    city: str | None = None
    state_province: str | None = None
    country_code: str | None = None
    sort_order: int = Field(ge=0)


class ResidenceHistoryCreate(BaseModel):
    person_id: uuid.UUID
    country_code: str = Field(min_length=2, max_length=3)
    status_or_purpose: str
    start_date: date
    end_date: date
    review_state: ReviewState = ReviewState.UNREVIEWED
    sort_order: int = Field(ge=0)


class TravelHistoryCreate(BaseModel):
    person_id: uuid.UUID
    country_code: str = Field(min_length=2, max_length=3)
    purpose: str
    entry_date: date
    exit_date: date
    review_state: ReviewState = ReviewState.UNREVIEWED
    sort_order: int = Field(ge=0)


class ReorderRequest(BaseModel):
    ordered_ids: list[uuid.UUID] = Field(min_length=1)


class OfficialAnswerWrite(BaseModel):
    question_code: str = Field(min_length=1, max_length=128)
    answer: OfficialAnswerValue = OfficialAnswerValue.UNKNOWN
    review_state: ReviewState = ReviewState.UNREVIEWED
    reviewed_by: str | None = None
    source_reference: str | None = None


class OfficialExplanationWrite(BaseModel):
    section_code: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1)
    review_state: ReviewState = ReviewState.UNREVIEWED
    reviewed_by: str | None = None


class RepresentativeRevisionCreate(BaseModel):
    family_name: str
    given_names: str
    organization_name: str | None = None
    unit: str | None = None
    street_number: str | None = None
    street_name: str | None = None
    city: str | None = None
    province: str | None = None
    country_code: str | None = None
    postal_code: str | None = None
    phone_country_code: str | None = None
    phone_number: str | None = None
    email: str | None = None
    category: str | None = None
    membership_number: str | None = None
    membership_province: str | None = None
    other_category_details: str | None = None
    supervising_lawyer: str | None = None
    supervising_lawyer_membership: str | None = None
    created_by: str | None = None


class RepresentativeProfileCreate(BaseModel):
    profile_name: str = Field(min_length=1, max_length=255)
    revision: RepresentativeRevisionCreate


class RepresentativeAuthorizationWrite(BaseModel):
    representative_person_id: uuid.UUID
    profile_revision_id: uuid.UUID
    action: str = Field(min_length=1, max_length=64)
    cancelled_representative_person_id: uuid.UUID | None = None
    cancelled_organization_name: str | None = None
    review_state: ReviewState = ReviewState.UNREVIEWED
    reviewed_by: str | None = None


class ProvenanceCreate(BaseModel):
    entity_type: ProvenanceEntityType
    entity_id: uuid.UUID
    field_key: str = Field(min_length=1, max_length=128)
    source_type: str = Field(min_length=1, max_length=32)
    source_reference: str = Field(min_length=1)
    source_digest: str | None = Field(default=None, max_length=64)
    confidence: float | None = Field(default=None, ge=0, le=1)
    review_state: ReviewState = ReviewState.UNREVIEWED
    reviewed_by: str | None = None


class GenericRead(ReadModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")
    id: uuid.UUID


class CanadaApplicationBundle(BaseModel):
    application: CanadaApplicationRead
    roles: list[dict[str, Any]]
    biographies: list[dict[str, Any]]
    citizenships: list[dict[str, Any]]
    identifiers: list[dict[str, Any]]
    contacts: list[dict[str, Any]]
    addresses: list[dict[str, Any]]
    applicant_residences: list[dict[str, Any]]
    travel_documents: list[dict[str, Any]]
    trip_plan: dict[str, Any] | None
    funding_sources: list[dict[str, Any]]
    hosts: list[dict[str, Any]]
    organizations: list[dict[str, Any]]
    family_relationships: list[dict[str, Any]]
    education: list[dict[str, Any]]
    activities: list[dict[str, Any]]
    residence_history: list[dict[str, Any]]
    travel_history: list[dict[str, Any]]
    official_answers: list[dict[str, Any]]
    official_explanations: list[dict[str, Any]]
    representative_authorization: dict[str, Any] | None
    provenance: list[dict[str, Any]]
