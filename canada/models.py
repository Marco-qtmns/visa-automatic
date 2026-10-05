from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IdentityData:
    full_name: str = ""

    # Must eventually be collected separately.
    # Do not infer these from full_name.
    family_name: str = ""
    given_names: str = ""

    other_names: str = ""
    date_of_birth: str = ""
    birth_country: str = ""
    city_of_birth: str = ""
    state_of_birth: str = ""
    nationality: str = ""
    other_citizenship: str = ""

    residence_country: str = ""
    residence_status: str = ""
    residence_since: str = ""
    previous_residence_5y: str = ""

    marital_status: str = ""
    languages: str = ""
    language_test_answer: str = ""

    # Current intake does not clearly provide this as a separate field.
    sex: str = ""


@dataclass
class PassportData:
    number: str = ""
    issuing_country: str = ""
    issue_date: str = ""
    expiry_date: str = ""

    has_other_valid_passport: str = ""
    other_passport_details: str = ""

    identity_number: str = ""
    identity_country: str = ""
    identity_issue_date: str = ""
    identity_expiry_date: str = ""

    green_card_details: str = ""


@dataclass
class ContactData:
    address: str = ""
    # Staff-confirmed, never guessed from a city, postcode or address line.
    country: str = ""
    mailing_same_as_residential: str = ""
    mailing_address: str = ""
    city: str = ""
    state: str = ""
    postcode: str = ""
    email: str = ""
    phone: str = ""


@dataclass
class TripData:
    purpose: str = ""
    arrival_date: str = ""
    departure_date: str = ""
    duration_days: str = ""
    estimated_spend: str = ""
    estimated_spend_currency: str = ""
    funds_source_reference: str = ""
    available_funds_cad: str = ""

    payer: str = ""
    payer_details: str = ""

    visiting_person_or_institution: str = ""
    host_name: str = ""
    relationship: str = ""
    family_relationship: str = ""
    host_status: str = ""
    host_address: str = ""
    host_postcode: str = ""
    host_phone: str = ""
    host_email: str = ""


@dataclass
class EducationData:
    level: str = ""
    institution: str = ""
    course: str = ""
    start_date: str = ""
    end_date: str = ""
    country: str = ""
    city: str = ""
    state: str = ""
    post_secondary_details: str = ""


@dataclass
class EmploymentData:
    start_date: str = ""
    profession: str = ""
    duties: str = ""
    organization: str = ""
    city: str = ""
    state: str = ""
    has_other_activities_answer: str = ""


@dataclass
class Activity:
    id: str = ""
    status: str = ""
    description: str = ""
    raw_source: str = ""
    activity_type: str = ""
    start_date: str = ""
    end_date: str = ""
    position: str = ""
    organization: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    ongoing_answer: str = ""
    has_more_activities_answer: str = ""
    source_block_index: int = 0
    source_role: str = ""


@dataclass
class RelationshipData:
    marriage_start_date: str = ""
    spouse_family_name: str = ""
    spouse_given_names: str = ""
    spouse_birth_country: str = ""
    spouse_date_of_birth: str = ""
    spouse_occupation: str = ""
    spouse_residence_answer: str = ""
    spouse_address: str = ""
    spouse_accompanying_answer: str = ""
    has_previous_relationship: str = ""
    former_spouse_family_name: str = ""
    former_spouse_given_names: str = ""
    former_spouse_birth_country: str = ""
    former_spouse_full_name: str = ""
    former_spouse_date_of_birth: str = ""
    previous_relationship_type: str = ""
    previous_start_date: str = ""
    previous_end_date: str = ""
    former_spouse_birth_city: str = ""
    former_spouse_occupation: str = ""
    former_spouse_address: str = ""
    former_spouse_residence_answer: str = ""
    former_spouse_accompanying_answer: str = ""


@dataclass
class FamilyMember:
    id: str = ""
    guardian_status: str = ""
    # These are explicit manual corrections, never inferred from source text.
    family_name: str = ""
    given_names: str = ""
    birth_country: str = ""
    confirmed_role: str = ""
    # Source order is classified only by the verified intake contract.
    source_block_index: int = 0
    source_role: str = ""
    relationship: str = ""
    full_name: str = ""
    date_of_birth: str = ""
    birth_place: str = ""
    marital_status: str = ""
    occupation: str = ""
    address: str = ""
    postcode: str = ""
    death_details: str = ""
    accompanying_answer: str = ""
    has_more_children_answer: str = ""


@dataclass
class FamilyData:
    has_children_answer: str = ""
    parents: list[FamilyMember] = field(default_factory=list)
    children: list[FamilyMember] = field(default_factory=list)
    siblings_abroad_answer: str = ""
    siblings_abroad_details: str = ""


@dataclass
class HistoryData:
    # Preserve original narratives alongside deterministic parsed records.
    previous_residences: str = ""
    travelled_abroad_answer: str = ""
    travel_details: str = ""
    previous_canada_visa_answer: str = ""
    canada_refusal_answer: str = ""
    other_refusal_answer: str = ""
    previously_in_canada_answer: str = ""
    immigration_details: str = ""
    criminal_history_answer: str = ""
    service_history_answer: str = ""
    immigration_problems_answer: str = ""
    overstay_answer: str = ""
    declaration_details: str = ""


@dataclass
class HistoryRecord:
    """A reviewable proposal. A digest binds confirmation to the exact content."""
    country: str = ""
    status_or_purpose: str = ""
    start_date: str = ""
    end_date: str = ""
    source_text: str = ""
    source_role: str = ""
    source_block_index: int = 0
    confirmation_digest: str = ""
    parsed_digest: str = ""
    id: str = ""


@dataclass
class StaffReviewData:
    application_date: str = ""
    legal_guardian: str = ""
    uci: str = ""
    native_language: str = ""
    preferred_language: str = ""
    service_language: str = ""
    guardianship_notes: str = ""
    guardianship_document_reference: str = ""
    additional_children_notes: str = ""
    additional_activities_notes: str = ""
    history_reviewed: str = ""
    follow_up_notes: str = ""


@dataclass
class LetterData:
    introduction: str = ""
    reason_for_canada: str = ""
    planned_activities: str = ""
    return_plans: str = ""
    occupation_in_brazil: str = ""
    close_relatives_abroad: str = ""


@dataclass
class DocumentReference:
    # References only: never download a client's attachments during import.
    source_role: str = ""
    source_block_index: int = 0
    category: str = ""
    references: str = ""


@dataclass
class ReviewChange:
    path: str
    previous_value: str
    corrected_value: str
    reviewed_at: str


@dataclass
class OfficialFormReview:
    """Staff-confirmed official answers; never inferred from broad intake text.

    Yes/no fields refer to the full corresponding IMM5257 question, not just
    one clause. Keep blank when any clause remains unknown.
    """
    residential_unit: str = ""
    residential_street_number: str = ""
    residential_street_name: str = ""
    mailing_po_box: str = ""
    mailing_unit: str = ""
    mailing_street_number: str = ""
    mailing_street_name: str = ""
    mailing_city: str = ""
    mailing_country: str = ""
    mailing_province: str = ""
    mailing_postcode: str = ""
    previous_residence_over_six_months: str = ""
    applying_from_residence_country: str = ""
    post_secondary_education: str = ""
    tuberculosis_or_close_contact_last_two_years: str = ""
    disorder_requiring_social_or_health_services: str = ""
    medical_details: str = ""
    canada_overstay_unauthorized_work_or_study: str = ""
    visa_refusal_denied_entry_or_removal_any_country: str = ""
    previously_applied_to_enter_or_remain_canada: str = ""
    immigration_explanation: str = ""
    committed_arrested_charged_or_convicted_any_country: str = ""
    criminal_details: str = ""
    military_militia_civil_defence_security_or_police: str = ""
    service_details: str = ""
    associated_with_violent_or_criminal_organization: str = ""
    witnessed_or_participated_in_ill_treatment_looting_desecration: str = ""


@dataclass
class CanadaRepresentative:
    # Internal, case-specific settings. Never copied from an Australian recipient
    # or from the Canadian host. Actions/categories require explicit selection.
    family_name: str = ""
    given_names: str = ""
    organization: str = ""
    unit: str = ""
    street_number: str = ""
    street_name: str = ""
    city: str = ""
    province: str = ""
    country: str = ""
    postcode: str = ""
    phone_country_code: str = ""
    phone_number: str = ""
    email: str = ""
    action: str = ""
    category: str = ""
    membership_number: str = ""
    membership_province: str = ""
    other_category_details: str = ""
    supervising_lawyer: str = ""
    supervising_lawyer_membership: str = ""
    cancelled_family_name: str = ""
    cancelled_given_names: str = ""
    cancelled_organization: str = ""


@dataclass
class ValueOrigin:
    value: str = ""
    source_type: str = ""
    source_ref: str = ""
    confirmed: bool = False
    source_digest: str = ""
    context_digest: str = ""


@dataclass
class CanadaCase:
    case_id: str = ""
    schema_version: str = ""
    provenance: dict[str, ValueOrigin] = field(default_factory=dict)
    overrides: dict[str, ValueOrigin] = field(default_factory=dict)
    identity: IdentityData = field(default_factory=IdentityData)
    passport: PassportData = field(default_factory=PassportData)
    contact: ContactData = field(default_factory=ContactData)
    trip: TripData = field(default_factory=TripData)
    education: EducationData = field(default_factory=EducationData)
    employment: EmploymentData = field(default_factory=EmploymentData)

    relationships: RelationshipData = field(default_factory=RelationshipData)
    family: FamilyData = field(default_factory=FamilyData)
    history: HistoryData = field(default_factory=HistoryData)
    staff_review: StaffReviewData = field(default_factory=StaffReviewData)
    representative: CanadaRepresentative = field(default_factory=CanadaRepresentative)
    official_review: OfficialFormReview = field(default_factory=OfficialFormReview)
    letters: LetterData = field(default_factory=LetterData)
    documents: list[DocumentReference] = field(default_factory=list)
    declaration_acceptance: str = ""

    activities: list[Activity] = field(default_factory=list)
    residence_records: list[HistoryRecord] = field(default_factory=list)
    travel_records: list[HistoryRecord] = field(default_factory=list)
    narrative_proposals_digest: str = ""

    # Preserves every original answer, including duplicate question names.
    raw_response: dict[str, list[str]] = field(default_factory=dict)

    source_email: str = ""
    import_profile: str = "legacy"
    source_headers: list[str] = field(default_factory=list)
    source_header_sha256: str = ""
    review_changes: list[ReviewChange] = field(default_factory=list)

    def validation_issues(self) -> list[str]:
        from .validation import validate_case, issue_text
        return [issue_text(issue) for issue in validate_case(self).issues]

    def display_name(self) -> str:
        """UI label only; do not store a manufactured full name as source data."""
        return self.identity.full_name or ', '.join(filter(None, (self.identity.family_name, self.identity.given_names))) or '(no name)'
