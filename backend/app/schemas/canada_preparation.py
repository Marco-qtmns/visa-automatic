from __future__ import annotations

from datetime import date, datetime
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict


class FrozenValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PreparationIssue(FrozenValue):
    code: Literal[
        "missing_value", "review_required", "unresolved_import_conflict",
        "unresolved_fact_conflict", "missing_selection", "invalid_cardinality",
        "inconsistent_data", "blocking_requirement", "unsupported_value",
        "missing_collection_record", "incomplete_collection", "ambiguous_reference",
    ]
    path: str
    section: str
    label: str
    severity: Literal["blocking", "warning"]
    blocking: bool
    message: str
    action: str


class PreparationSection(FrozenValue):
    section: str
    label: str
    blocking_count: int
    warning_count: int
    issues: tuple[PreparationIssue, ...]


class PreparationReadinessResult(FrozenValue):
    ready: bool
    policy_version: str
    schema_version: str
    payload_hash: str | None
    issues: tuple[PreparationIssue, ...]
    warnings: tuple[PreparationIssue, ...]
    sections: tuple[PreparationSection, ...]
    blocking_count: int
    warning_count: int


class BiographyPayload(FrozenValue):
    date_of_birth: date
    other_names: str | None
    sex: str
    birth_city: str
    birth_state_province: str | None
    birth_country_code: str
    marital_status: str


class CitizenshipPayload(FrozenValue):
    country_code: str
    citizenship_type: str
    is_primary: bool
    sort_order: int


class IdentifierPayload(FrozenValue):
    identifier_type: str
    country_code: str
    value: str
    issue_date: date | None
    expiry_date: date | None


class ApplicantPayload(FrozenValue):
    family_name: str
    given_names: str
    display_name: str
    biography: BiographyPayload
    citizenships: tuple[CitizenshipPayload, ...]
    identifiers: tuple[IdentifierPayload, ...]


class ContactPayload(FrozenValue):
    type: Literal["email", "phone"]
    value: str
    country_code: str | None
    purpose: str
    is_primary: bool
    sort_order: int


class AddressPayload(FrozenValue):
    context: str
    po_box: str | None
    unit: str | None
    street_number: str | None
    street_name: str | None
    city: str | None
    state_province: str | None
    postal_code: str | None
    country_code: str | None
    unstructured_source_text: str | None


class ResidencePayload(FrozenValue):
    country_code: str
    immigration_status_code: str | None
    resident_since: date | None
    is_current: bool


class PassportPayload(FrozenValue):
    document_type: str
    number: str
    issuing_country_code: str
    issue_date: date
    expiry_date: date
    details: str | None
    has_other_valid_passport: bool
    other_passport_details: str | None


class SecondaryPassportPayload(FrozenValue):
    number: str
    issuing_country_code: str
    issue_date: date | None
    expiry_date: date
    details: str | None


class ApplicationPayload(FrozenValue):
    official_application_date: date
    native_language_code: str | None
    preferred_language_code: str | None
    service_language_code: str | None
    mailing_same_as_residential: bool | None


class TripPayload(FrozenValue):
    intake_purpose_text: str
    imm5257_purpose_code: str
    arrival_date: date
    departure_date: date
    available_funds_amount: str
    available_funds_currency: str
    funds_source_reference: str


class FundingPayload(FrozenValue):
    payer_kind: str
    party_name: str | None
    description: str | None
    amount: str | None
    currency: str | None
    is_primary: bool
    sort_order: int


class HostPayload(FrozenValue):
    host_type: str
    display_name: str
    relationship_to_applicant: str | None
    family_relationship: str | None
    immigration_status_in_canada: str | None
    address: AddressPayload | None
    email: str | None
    phone: str | None
    is_primary: bool
    sort_order: int


class RelatedPersonPayload(FrozenValue):
    family_name: str
    given_names: str
    date_of_birth: date | None
    birth_country_code: str | None
    marital_status: str | None
    occupation_text: str | None


class FamilyRelationshipPayload(FrozenValue):
    relationship_type: str
    parent_type: str | None
    guardian_status: str | None
    is_current: bool
    relationship_start_date: date | None
    relationship_end_date: date | None
    previous_relationship_type: str | None
    accompanying_applicant: bool | None
    residence_same_as_applicant: bool | None
    death_details: str | None
    address: AddressPayload | None
    related_person: RelatedPersonPayload
    sort_order: int


class EducationPayload(FrozenValue):
    level: str | None
    institution_name: str | None
    course: str | None
    details: str | None
    start_date: date | None
    end_date: date | None
    city: str | None
    state_province: str | None
    country_code: str | None
    is_primary: bool
    sort_order: int


class ActivityPayload(FrozenValue):
    activity_type: str | None
    position: str | None
    organization_name: str | None
    duties: str | None
    start_date: date | None
    end_date: date | None
    period_status: str
    city: str | None
    state_province: str | None
    country_code: str | None
    sort_order: int


class ResidenceHistoryPayload(FrozenValue):
    country_code: str
    status_or_purpose: str
    start_date: date
    end_date: date
    sort_order: int


class TravelHistoryPayload(FrozenValue):
    country_code: str
    purpose: str
    entry_date: date
    exit_date: date
    sort_order: int


class OfficialAnswerPayload(FrozenValue):
    question_code: str
    answer: Literal["yes", "no", "not_applicable"]


class OfficialExplanationPayload(FrozenValue):
    section_code: str
    text: str


class RepresentativePayload(FrozenValue):
    action: str
    revision_number: int
    family_name: str
    given_names: str
    organization_name: str | None
    unit: str | None
    street_number: str | None
    street_name: str | None
    city: str | None
    province: str | None
    country_code: str | None
    postal_code: str | None
    phone_country_code: str | None
    phone_number: str | None
    email: str | None
    category: str | None
    membership_number: str | None
    membership_province: str | None
    other_category_details: str | None
    supervising_lawyer: str | None
    supervising_lawyer_membership: str | None
    cancelled_representative_name: str | None
    cancelled_representative_family_name: str | None
    cancelled_representative_given_names: str | None
    cancelled_organization_name: str | None


class CanonicalPreparationPayload(FrozenValue):
    schema_version: str
    policy_version: str
    application: ApplicationPayload
    applicant: ApplicantPayload
    passport: PassportPayload
    secondary_passports: tuple[SecondaryPassportPayload, ...]
    contacts: tuple[ContactPayload, ...]
    residential_address: AddressPayload
    mailing_address: AddressPayload | None
    residences: tuple[ResidencePayload, ...]
    trip: TripPayload
    hosts: tuple[HostPayload, ...]
    funding: tuple[FundingPayload, ...]
    family: tuple[FamilyRelationshipPayload, ...]
    education: tuple[EducationPayload, ...]
    activities: tuple[ActivityPayload, ...]
    residence_history: tuple[ResidenceHistoryPayload, ...]
    travel_history: tuple[TravelHistoryPayload, ...]
    official_answers: tuple[OfficialAnswerPayload, ...]
    official_explanations: tuple[OfficialExplanationPayload, ...]
    representative: RepresentativePayload


class PreparationArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    preparation_run_id: uuid.UUID
    case_id: uuid.UUID
    artifact_type: str
    display_filename: str
    mime_type: str
    generator: str
    generator_version: str
    template_identifier: str
    template_hash: str
    file_hash: str
    created_at: datetime


class PreparationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    case_id: uuid.UUID
    status: str
    initiated_by: str
    payload_schema_version: str
    preparation_policy_version: str
    payload_hash: str
    adapter_version: str
    generator_version: str
    started_at: datetime
    completed_at: datetime | None
    error_code: str | None
    error_summary: str | None
    created_at: datetime


class PreparationRunDetail(PreparationRunRead):
    artifacts: tuple[PreparationArtifactRead, ...]


class PreparationStatusResult(BaseModel):
    readiness: PreparationReadinessResult
    latest_run: PreparationRunDetail | None
    current_run: PreparationRunDetail | None
    payload_hash: str | None
    package_status: Literal[
        "blocked", "not_generated", "generating", "current", "stale",
        "failed", "integrity_error", "submitted_discrepancy",
    ]
    integrity_error: str | None = None


class PreparationRequest(BaseModel):
    initiated_by: str
