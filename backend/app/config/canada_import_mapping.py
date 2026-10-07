"""Versioned, machine-readable M9 audit mapping (138 generator inputs)."""
from __future__ import annotations

from dataclasses import asdict, dataclass

MAPPING_VERSION = "m9b-2"

@dataclass(frozen=True)
class MappingEntry:
    legacy_path: str
    canonical_target: str
    source_classification: str
    review_policy: str
    transform: str
    conflict_policy: str


GROUPS = {
    "identity": ["family_name", "given_names", "other_names", "date_of_birth", "birth_country", "city_of_birth", "state_of_birth", "nationality", "other_citizenship", "residence_country", "residence_status", "residence_since", "marital_status", "sex"],
    "passport": ["number", "issuing_country", "issue_date", "expiry_date", "has_other_valid_passport", "other_passport_details", "identity_number", "identity_country", "identity_issue_date", "identity_expiry_date"],
    "contact": ["address", "country", "mailing_same_as_residential", "mailing_address", "city", "state", "postcode", "email", "phone", "residential_unit", "residential_street_number", "residential_street_name", "mailing_po_box", "mailing_street_name"],
    "trip": ["purpose", "arrival_date", "departure_date", "available_funds_cad", "estimated_spend_currency", "funds_source_reference", "payer", "payer_details", "visiting_person_or_institution", "host_name", "relationship", "family_relationship", "host_status", "host_address", "host_phone", "host_email"],
    "education": ["level", "institution", "course", "start_date", "end_date", "country", "city", "state", "post_secondary_details"],
    "activities[*]": ["activity_type", "start_date", "end_date", "position", "organization", "duties", "city", "state", "country", "ongoing_answer", "status"],
    "relationships": ["marriage_start_date", "spouse_family_name", "spouse_given_names", "spouse_birth_country", "spouse_date_of_birth", "spouse_occupation", "spouse_address", "spouse_accompanying_answer", "has_previous_relationship", "former_spouse_family_name", "former_spouse_given_names", "former_spouse_date_of_birth", "previous_relationship_type", "previous_start_date", "previous_end_date"],
    "family.members[*]": ["relationship", "family_name", "given_names", "date_of_birth", "birth_country", "marital_status", "occupation", "address"],
    "residence_records[*]": ["country", "status_or_purpose", "start_date", "end_date"],
    "travel_records[*]": ["country", "status_or_purpose", "start_date", "end_date"],
    "official_review": ["previous_residence_over_six_months", "applying_from_residence_country", "post_secondary_education", "tuberculosis_or_close_contact_last_two_years", "disorder_requiring_social_or_health_services", "canada_overstay_unauthorized_work_or_study", "visa_refusal_denied_entry_or_removal_any_country", "previously_applied_to_enter_or_remain_canada", "committed_arrested_charged_or_convicted_any_country", "military_militia_civil_defence_security_or_police"],
    "representative": ["family_name", "given_names", "organization", "unit", "street_number", "street_name", "city", "province", "country", "postcode", "phone_country_code", "phone_number", "email", "action", "category", "membership_number", "membership_province", "other_category_details", "supervising_lawyer", "supervising_lawyer_membership", "cancelled_family_name", "cancelled_organization"],
    "staff_review": ["application_date"],
}

COUNTRY_CODE_MAPPING_PATHS = frozenset({
    "identity.birth_country",
    "identity.nationality",
    "identity.other_citizenship",
    "identity.residence_country",
    "passport.issuing_country",
    "passport.identity_country",
    "contact.country",
    "education.country",
    "activities[*].country",
    "relationships.spouse_birth_country",
    "family.members[*].birth_country",
    "residence_records[*].country",
    "travel_records[*].country",
    "representative.country",
})


def _target(path: str) -> str:
    group, field = path.rsplit(".", 1)
    if group == "identity":
        return {"family_name": "applicant.person.last_name", "given_names": "applicant.person.first_name", "nationality": "applicant.citizenships.primary", "other_citizenship": "applicant.citizenships.other", "residence_country": "applicant.residence.country_code", "residence_status": "applicant.residence.immigration_status_code", "residence_since": "applicant.residence.resident_since"}.get(field, f"applicant.biography.{field}")
    if group == "passport": return f"applicant.travel_document.{field}"
    if group == "contact": return f"applicant.contact_or_address.{field}"
    if group == "trip": return "trip_plan.intake_purpose_text" if field == "purpose" else f"trip_plan.{field}"
    if group == "education": return f"education_records[*].{field}"
    if group == "activities[*]": return f"activity_records[*].{field}"
    if group == "relationships": return f"family_relationships.{field}"
    if group == "family.members[*]": return f"family_relationships[*].{field}"
    if group == "residence_records[*]": return f"residence_history_records[*].{field}"
    if group == "travel_records[*]": return f"travel_history_records[*].{field}"
    if group == "official_review": return f"official_application_answers.{field}"
    if group == "representative":
        if field == "action": return "representative_authorization.action"
        if field == "cancelled_family_name": return "representative_authorization.cancelled_representative_person_id"
        if field == "cancelled_organization": return "representative_authorization.cancelled_organization_name"
        return f"representative_snapshot.{field}"
    return f"canada_application.{field}"


def _classification(path: str) -> str:
    if path in {"representative.action", "representative.cancelled_family_name", "representative.cancelled_organization"}: return "legacy_staff_review"
    if path.startswith("representative."): return "representative_profile"
    if path.startswith("official_review.") or path.startswith("staff_review."): return "legacy_staff_review"
    if path.startswith(("residence_records[*].", "travel_records[*].")): return "legacy_narrative_derived"
    if path.endswith(".status"): return "legacy_derived"
    return "applicant_direct"


def _review_policy(group: str, field: str) -> str:
    if group in {"official_review", "representative", "staff_review"}:
        return "explicit_review"
    if group == "trip" and (field.startswith("host_") or field in {
        "visiting_person_or_institution", "relationship", "family_relationship",
        "payer", "payer_details",
    }):
        return "explicit_review"
    if group == "passport" and field in {"has_other_valid_passport", "other_passport_details"}:
        return "explicit_review"
    if field in {"address", "mailing_address", "spouse_address"}:
        return "explicit_review"
    return "safe_direct_batch"


AUDITED_GENERATOR_MAPPINGS = tuple(
    MappingEntry(
        legacy_path=f"{group}.{field}", canonical_target=_target(f"{group}.{field}"),
        source_classification=_classification(f"{group}.{field}"),
        review_policy=_review_policy(group, field),
        transform=(
            "country_iso_alpha3" if f"{group}.{field}" in COUNTRY_CODE_MAPPING_PATHS
            else "date" if field.endswith("date") or field in {
                "start_date", "end_date", "date_of_birth", "application_date",
            }
            else "verbatim"
        ),
        conflict_policy="never_overwrite_reviewed",
    )
    for group, fields in GROUPS.items() for field in fields
)

assert len(AUDITED_GENERATOR_MAPPINGS) == 138

MAPPING_SPEC_JSON = tuple(asdict(entry) for entry in AUDITED_GENERATOR_MAPPINGS)
