"""Versioned M9C readiness policy and 138-path semantic payload projection.

This is an internal Visa Automatic preparation standard.  It deliberately does
not claim to be a statement of Canadian immigration law.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .canada_import_mapping import AUDITED_GENERATOR_MAPPINGS


POLICY_VERSION = "m9c-1"
PAYLOAD_SCHEMA_VERSION = "m9d-1"

PolicyKind = Literal[
    "required_value", "required_review", "conditional",
    "collection_requirement", "optional_for_current_generator",
    "derived", "not_applicable",
]


@dataclass(frozen=True)
class PreparationPolicyRule:
    path: str
    kind: PolicyKind
    section: str
    label: str
    forms: tuple[str, ...]
    condition: str | None = None
    review_mode: str | None = None


@dataclass(frozen=True)
class PayloadProjection:
    legacy_path: str
    canonical_source: str
    payload_path: str
    projection: Literal["source", "derived"]


OFFICIAL_QUESTION_CODES = (
    "previous_residence_over_six_months",
    "applying_from_residence_country",
    "post_secondary_education",
    "tuberculosis_or_close_contact_last_two_years",
    "disorder_requiring_social_or_health_services",
    "canada_overstay_unauthorized_work_or_study",
    "visa_refusal_denied_entry_or_removal_any_country",
    "previously_applied_to_enter_or_remain_canada",
    "committed_arrested_charged_or_convicted_any_country",
    "military_militia_civil_defence_security_or_police",
    "associated_with_violent_or_criminal_organization",
    "witnessed_or_participated_in_ill_treatment_looting_desecration",
)

OFFICIAL_EXPLANATION_CONDITIONS = {
    "medical_details": (
        "tuberculosis_or_close_contact_last_two_years",
        "disorder_requiring_social_or_health_services",
    ),
    "immigration_explanation": (
        "canada_overstay_unauthorized_work_or_study",
        "visa_refusal_denied_entry_or_removal_any_country",
        "previously_applied_to_enter_or_remain_canada",
    ),
    "criminal_details": ("committed_arrested_charged_or_convicted_any_country",),
    "service_details": ("military_militia_civil_defence_security_or_police",),
}

REPRESENTATIVE_MEMBERSHIP_CATEGORIES = frozenset({
    "Unpaid - CICC member",
    "Unpaid - law society or student-at-law",
    "Unpaid - Quebec notary",
    "Paid - CICC member",
    "Paid - law society or student-at-law",
    "Paid - Quebec notary",
})
REPRESENTATIVE_ACTIONS = frozenset({
    "Appoint a representative", "Update representative contact information",
    "Cancel a representative", "Cancel and appoint a new representative",
    "Withdraw as representative",
})
REPRESENTATIVE_CATEGORIES = frozenset({
    "Unpaid - friend or family", "Unpaid - CICC member", "Unpaid - other",
    "Unpaid - law society or student-at-law", "Unpaid - Quebec notary",
    "Paid - CICC member", "Paid - law society or student-at-law",
    "Paid - Quebec notary",
})
REPRESENTATIVE_LAW_SOCIETY_CATEGORIES = frozenset({
    "Unpaid - law society or student-at-law",
    "Paid - law society or student-at-law",
})


PREPARATION_POLICY = (
    PreparationPolicyRule("application.applicant", "required_value", "applicant", "Selected applicant", ("IMM5257", "IMM5707", "IMM5476")),
    PreparationPolicyRule("applicant.family_name", "required_value", "applicant", "Family name", ("IMM5257", "IMM5707", "IMM5476")),
    PreparationPolicyRule("applicant.given_names", "required_value", "applicant", "Given names", ("IMM5257", "IMM5707", "IMM5476")),
    PreparationPolicyRule("applicant.biography.date_of_birth", "required_value", "applicant", "Date of birth", ("IMM5257", "IMM5707", "IMM5476")),
    PreparationPolicyRule("applicant.biography.sex", "required_value", "applicant", "Sex", ("IMM5257", "IMM5707")),
    PreparationPolicyRule("applicant.biography.birth_city", "required_value", "applicant", "City of birth", ("IMM5257", "IMM5707")),
    PreparationPolicyRule("applicant.biography.birth_country_code", "required_value", "applicant", "Country of birth", ("IMM5257", "IMM5707")),
    PreparationPolicyRule("applicant.biography.marital_status", "required_value", "applicant", "Marital status", ("IMM5257", "IMM5707")),
    PreparationPolicyRule("applicant.citizenship.primary", "required_value", "applicant", "Primary citizenship", ("IMM5257",)),
    PreparationPolicyRule("applicant.current_residence", "required_value", "contact", "Current country of residence", ("IMM5257",)),
    PreparationPolicyRule("applicant.passport.primary", "required_value", "passport", "Primary passport", ("IMM5257",)),
    PreparationPolicyRule("applicant.passport.number", "required_review", "passport", "Passport number", ("IMM5257",), review_mode="derived_source_must_be_reviewed"),
    PreparationPolicyRule("applicant.passport.issue_date", "required_review", "passport", "Passport issue date", ("IMM5257",), review_mode="derived_source_must_be_reviewed"),
    PreparationPolicyRule("applicant.passport.expiry_date", "required_review", "passport", "Passport expiry date", ("IMM5257",), review_mode="derived_source_must_be_reviewed"),
    PreparationPolicyRule("applicant.passport.secondary", "conditional", "passport", "Other valid passport", ("IMM5257",), condition="canonical other-passport details exist"),
    PreparationPolicyRule("applicant.residential_address", "required_review", "contact", "Residential address", ("IMM5257",), review_mode="entity_review_state"),
    PreparationPolicyRule("application.mailing_same_as_residential", "required_value", "contact", "Mailing-address choice", ("IMM5257",)),
    PreparationPolicyRule("applicant.contact.email", "required_value", "contact", "Primary email", ("IMM5257", "IMM5476")),
    PreparationPolicyRule("applicant.contact.phone", "required_value", "contact", "Primary phone", ("IMM5257",)),
    PreparationPolicyRule("application.official_application_date", "required_review", "application", "Official application package date", ("IMM5257", "IMM5707", "IMM5476"), review_mode="application_date_review_state"),
    PreparationPolicyRule("trip.intake_purpose_text", "required_value", "trip", "Travel purpose", ("IMM5257",)),
    PreparationPolicyRule("trip.imm5257_purpose_code", "required_review", "trip", "Reviewed IMM5257 purpose", ("IMM5257",), review_mode="purpose_review_state"),
    PreparationPolicyRule("trip.arrival_date", "required_value", "trip", "Arrival date", ("IMM5257",)),
    PreparationPolicyRule("trip.departure_date", "required_value", "trip", "Departure date", ("IMM5257",)),
    PreparationPolicyRule("trip.available_funds_amount", "required_value", "funding", "Available funds", ("IMM5257",)),
    PreparationPolicyRule("trip.available_funds_currency", "required_value", "funding", "Funds currency", ("IMM5257",)),
    PreparationPolicyRule("trip.funds_source_reference", "required_value", "funding", "Funds source", ("IMM5257",)),
    PreparationPolicyRule("activities", "collection_requirement", "activities", "Applicant activity history", ("IMM5257",)),
    PreparationPolicyRule("official_answers", "collection_requirement", "official_answers", "Reviewed official answers", ("IMM5257",)),
    PreparationPolicyRule("representative.authorization", "required_review", "representative", "Representative authorization", ("IMM5476",), review_mode="entity_review_state"),
    PreparationPolicyRule("host.primary", "conditional", "host", "Primary host", ("IMM5257",), condition="confirmed host.exists is true"),
    PreparationPolicyRule("funding.primary", "conditional", "funding", "Primary funding source", ("IMM5257",), condition="confirmed sponsor.exists is true"),
    PreparationPolicyRule("funding.sponsor_person", "conditional", "funding", "Sponsor person", ("IMM5257",), condition="confirmed sponsor.exists is true"),
    PreparationPolicyRule("education.primary", "conditional", "education", "Primary post-secondary education", ("IMM5257",), condition="reviewed post_secondary_education answer is yes"),
    PreparationPolicyRule("official_explanations", "conditional", "official_answers", "Official answer explanations", ("IMM5257",), condition="a configured explanation-trigger answer is yes"),
    PreparationPolicyRule("mailing_address", "conditional", "contact", "Mailing address", ("IMM5257",), condition="mailing address differs from residential address"),
    PreparationPolicyRule("applicant.other_names", "optional_for_current_generator", "applicant", "Other names", ("IMM5257",)),
    PreparationPolicyRule("applicant.other_citizenship", "optional_for_current_generator", "applicant", "Other citizenship", ("IMM5257",)),
)


def _payload_path(legacy_path: str, canonical_target: str) -> str:
    group, field = legacy_path.rsplit(".", 1)
    if group == "identity":
        return {
            "family_name": "applicant.family_name", "given_names": "applicant.given_names",
            "other_names": "applicant.biography.other_names", "date_of_birth": "applicant.biography.date_of_birth",
            "birth_country": "applicant.biography.birth_country_code", "city_of_birth": "applicant.biography.birth_city",
            "state_of_birth": "applicant.biography.birth_state_province", "nationality": "applicant.citizenships[*].country_code",
            "other_citizenship": "applicant.citizenships[*].country_code", "residence_country": "residences[*].country_code",
            "residence_status": "residences[*].immigration_status_code", "residence_since": "residences[*].resident_since",
            "marital_status": "applicant.biography.marital_status", "sex": "applicant.biography.sex",
        }[field]
    if group == "passport":
        return {
            "number": "passport.number", "issuing_country": "passport.issuing_country_code",
            "issue_date": "passport.issue_date", "expiry_date": "passport.expiry_date",
            "has_other_valid_passport": "passport.has_other_valid_passport",
            "other_passport_details": "passport.other_passport_details",
            "identity_number": "applicant.identifiers[*].value", "identity_country": "applicant.identifiers[*].country_code",
            "identity_issue_date": "applicant.identifiers[*].issue_date", "identity_expiry_date": "applicant.identifiers[*].expiry_date",
        }[field]
    if group == "contact":
        if field == "mailing_same_as_residential": return "application.mailing_same_as_residential"
        if field.startswith("mailing_") or field == "mailing_address":
            return {"mailing_address":"mailing_address.unstructured_source_text", "mailing_po_box":"mailing_address.po_box", "mailing_street_name":"mailing_address.street_name"}[field]
        if field in {"email", "phone"}: return f"contacts[type={field}].value"
        return {"address":"residential_address.unstructured_source_text", "country":"residential_address.country_code", "city":"residential_address.city", "state":"residential_address.state_province", "postcode":"residential_address.postal_code", "residential_unit":"residential_address.unit", "residential_street_number":"residential_address.street_number", "residential_street_name":"residential_address.street_name"}[field]
    if group == "trip":
        if field.startswith("host_") or field in {"visiting_person_or_institution", "relationship", "family_relationship"}:
            return {"visiting_person_or_institution":"hosts[*].host_type", "host_name":"hosts[*].display_name", "relationship":"hosts[*].relationship_to_applicant", "family_relationship":"hosts[*].family_relationship", "host_status":"hosts[*].immigration_status_in_canada", "host_address":"hosts[*].address", "host_phone":"hosts[*].phone", "host_email":"hosts[*].email"}[field]
        if field in {"payer", "payer_details"}: return "funding[*].payer_kind" if field == "payer" else "funding[*].description"
        return {"purpose":"trip.intake_purpose_text", "available_funds_cad":"trip.available_funds_amount", "estimated_spend_currency":"trip.available_funds_currency"}.get(field, f"trip.{field}")
    if group == "education": return f"education[*]." + {"institution":"institution_name", "country":"country_code", "state":"state_province", "post_secondary_details":"details"}.get(field, field)
    if group == "activities[*]": return f"activities[*]." + {"organization":"organization_name", "country":"country_code", "state":"state_province", "status":"period_status", "ongoing_answer":"period_status"}.get(field, field)
    if group == "relationships":
        if field == "has_previous_relationship": return "family[*].relationship_type"
        if field == "marriage_start_date": return "family[*].relationship_start_date"
        if field == "spouse_accompanying_answer": return "family[*].accompanying_applicant"
        if field == "previous_start_date": return "family[*].relationship_start_date"
        if field == "previous_end_date": return "family[*].relationship_end_date"
        if field == "previous_relationship_type": return "family[*].previous_relationship_type"
        if field == "spouse_address": return "family[*].address"
        suffix = field.removeprefix("spouse_").removeprefix("former_spouse_")
        return "family[*].related_person." + {"family_name":"family_name", "given_names":"given_names", "birth_country":"birth_country_code", "date_of_birth":"date_of_birth", "occupation":"occupation_text"}[suffix]
    if group == "family.members[*]":
        if field == "relationship": return "family[*].relationship_type"
        if field == "address": return "family[*].address"
        return "family[*].related_person." + {"family_name":"family_name", "given_names":"given_names", "date_of_birth":"date_of_birth", "birth_country":"birth_country_code", "marital_status":"marital_status", "occupation":"occupation_text"}[field]
    if group == "residence_records[*]": return f"residence_history[*]." + {"country":"country_code"}.get(field, field)
    if group == "travel_records[*]": return f"travel_history[*]." + {"country":"country_code", "status_or_purpose":"purpose", "start_date":"entry_date", "end_date":"exit_date"}.get(field, field)
    if group == "official_review": return f"official_answers[question_code={field}].answer"
    if group == "representative": return f"representative." + {"organization":"organization_name", "country":"country_code", "postcode":"postal_code", "cancelled_family_name":"cancelled_representative_family_name", "cancelled_organization":"cancelled_organization_name"}.get(field, field)
    return "application.official_application_date"


PAYLOAD_PROJECTIONS = tuple(
    PayloadProjection(
        legacy_path=item.legacy_path,
        canonical_source=item.canonical_target,
        payload_path=_payload_path(item.legacy_path, item.canonical_target),
        projection="derived" if item.legacy_path.endswith((".ongoing_answer", ".status", ".has_other_valid_passport", ".host_name", ".has_previous_relationship", ".cancelled_family_name")) else "source",
    )
    for item in AUDITED_GENERATOR_MAPPINGS
)

assert len(PAYLOAD_PROJECTIONS) == 138
assert len({item.legacy_path for item in PAYLOAD_PROJECTIONS}) == 138

POLICY_SPEC_JSON = tuple(asdict(item) for item in PREPARATION_POLICY)
PROJECTION_SPEC_JSON = tuple(asdict(item) for item in PAYLOAD_PROJECTIONS)
