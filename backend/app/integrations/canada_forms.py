from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from canada.models import Activity, CanadaCase, FamilyMember, HistoryRecord
from canada.preparation import record_digest

from ..schemas.canada_preparation import CanonicalPreparationPayload


ADAPTER_VERSION = "m9d-1"
GENERATOR_VERSION = "legacy-canada-xfa-1"
MANDATORY_ARTIFACT_TYPES = frozenset({"imm5257", "imm5707", "imm5476"})
CONTINUATION_ARTIFACT_TYPE = "imm5257_continuation"


@dataclass(frozen=True)
class GeneratedArtifactResult:
    artifact_type: str
    filename: str
    mime_type: str
    content: bytes
    generator: str
    generator_version: str
    template_identifier: str
    template_hash: str


class CanadaFormGeneratorAdapter(Protocol):
    adapter_version: str
    generator_version: str

    def generate(self, payload: CanonicalPreparationPayload) -> tuple[GeneratedArtifactResult, ...]: ...


def continuation_required(payload: CanonicalPreparationPayload) -> bool:
    address_fallback = bool(
        payload.residential_address.unstructured_source_text
        and not payload.residential_address.street_name
    )
    return bool(
        len(payload.activities) > 3
        or payload.residence_history
        or payload.travel_history
        or address_fallback
    )


class LegacyCanadaFormGeneratorAdapter:
    """The only boundary allowed to know the legacy CanadaCase/PDF generator."""

    adapter_version = ADAPTER_VERSION
    generator_version = GENERATOR_VERSION

    def __init__(self, *, template_dir: Path | None = None):
        self.template_dir = template_dir

    def generate(self, payload: CanonicalPreparationPayload) -> tuple[GeneratedArtifactResult, ...]:
        from canada.pdf_drafts import ROOT, generate_prepared_drafts

        legacy = self.to_legacy_case(payload)
        with tempfile.TemporaryDirectory(prefix="visa-automatic-canada-") as temporary:
            output = Path(temporary) / "generated"
            report = generate_prepared_drafts(legacy, output, self.template_dir)
            matrix = json.loads((ROOT / "canada/coverage_matrix.yaml").read_text(encoding="utf-8"))
            templates = matrix["templates"]
            manifest = []
            for artifact_type, form in (("imm5257", "IMM5257"), ("imm5707", "IMM5707"), ("imm5476", "IMM5476")):
                filename = f"{form}-DRAFT.pdf"
                manifest.append(GeneratedArtifactResult(
                    artifact_type=artifact_type, filename=filename, mime_type="application/pdf",
                    content=(output / filename).read_bytes(), generator="legacy_canada_xfa",
                    generator_version=self.generator_version,
                    template_identifier=templates[form]["file"], template_hash=templates[form]["sha256"],
                ))
            continuation = report.get("continuation")
            if continuation:
                filename = continuation["file"]
                source = ROOT / "canada/continuation.py"
                manifest.append(GeneratedArtifactResult(
                    artifact_type=CONTINUATION_ARTIFACT_TYPE, filename=filename,
                    mime_type="application/pdf", content=(output / filename).read_bytes(),
                    generator="legacy_canada_continuation", generator_version=self.generator_version,
                    template_identifier="reportlab:IMM5257-continuation",
                    template_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
                ))
            return tuple(manifest)

    @staticmethod
    def to_legacy_case(payload: CanonicalPreparationPayload) -> CanadaCase:
        value = CanadaCase(schema_version=payload.schema_version, import_profile="canonical_m9d")
        applicant = payload.applicant
        bio = applicant.biography
        value.identity.family_name = applicant.family_name
        value.identity.given_names = applicant.given_names
        value.identity.full_name = applicant.display_name
        value.identity.other_names = bio.other_names or ""
        value.identity.date_of_birth = bio.date_of_birth.isoformat()
        value.identity.birth_country = bio.birth_country_code
        value.identity.city_of_birth = bio.birth_city
        value.identity.state_of_birth = bio.birth_state_province or ""
        value.identity.marital_status = bio.marital_status
        value.identity.sex = bio.sex
        primary_citizenship = next(item for item in applicant.citizenships if item.is_primary)
        value.identity.nationality = primary_citizenship.country_code
        value.identity.other_citizenship = next((item.country_code for item in applicant.citizenships if not item.is_primary), "")
        current_residence = next(item for item in payload.residences if item.is_current)
        value.identity.residence_country = current_residence.country_code
        value.identity.residence_status = current_residence.immigration_status_code or ""
        value.identity.residence_since = current_residence.resident_since.isoformat() if current_residence.resident_since else ""

        passport = payload.passport
        value.passport.number = passport.number
        value.passport.issuing_country = passport.issuing_country_code
        value.passport.issue_date = passport.issue_date.isoformat()
        value.passport.expiry_date = passport.expiry_date.isoformat()
        value.passport.has_other_valid_passport = "Yes" if passport.has_other_valid_passport else "No"
        value.passport.other_passport_details = passport.other_passport_details or ""
        national_id = next((item for item in applicant.identifiers if item.identifier_type == "national_identity"), None)
        if national_id:
            value.passport.identity_number = national_id.value
            value.passport.identity_country = national_id.country_code
            value.passport.identity_issue_date = national_id.issue_date.isoformat() if national_id.issue_date else ""
            value.passport.identity_expiry_date = national_id.expiry_date.isoformat() if national_id.expiry_date else ""
        uci = next((item for item in applicant.identifiers if item.identifier_type == "uci"), None)
        value.staff_review.uci = uci.value if uci else ""

        residential = payload.residential_address
        value.contact.address = residential.unstructured_source_text or _address_line(residential)
        value.contact.country = residential.country_code or ""
        value.contact.city = residential.city or ""
        value.contact.state = residential.state_province or ""
        value.contact.postcode = residential.postal_code or ""
        value.contact.email = next(item.value for item in payload.contacts if item.type == "email" and item.is_primary)
        value.contact.phone = next(item.value for item in payload.contacts if item.type == "phone" and item.is_primary)
        value.contact.mailing_same_as_residential = "Yes" if payload.application.mailing_same_as_residential else "No"
        value.official_review.residential_unit = residential.unit or ""
        value.official_review.residential_street_number = residential.street_number or ""
        value.official_review.residential_street_name = residential.street_name or ""
        if payload.mailing_address:
            mailing = payload.mailing_address
            value.contact.mailing_address = mailing.unstructured_source_text or _address_line(mailing)
            value.official_review.mailing_po_box = mailing.po_box or ""
            value.official_review.mailing_unit = mailing.unit or ""
            value.official_review.mailing_street_number = mailing.street_number or ""
            value.official_review.mailing_street_name = mailing.street_name or ""
            value.official_review.mailing_city = mailing.city or ""
            value.official_review.mailing_country = mailing.country_code or ""
            value.official_review.mailing_province = mailing.state_province or ""
            value.official_review.mailing_postcode = mailing.postal_code or ""

        value.staff_review.application_date = payload.application.official_application_date.isoformat()
        value.staff_review.native_language = _language(payload.application.native_language_code)
        value.staff_review.preferred_language = _language(payload.application.preferred_language_code)
        value.staff_review.service_language = _language(payload.application.service_language_code)
        value.trip.purpose = payload.trip.imm5257_purpose_code
        value.trip.arrival_date = payload.trip.arrival_date.isoformat()
        value.trip.departure_date = payload.trip.departure_date.isoformat()
        value.trip.available_funds_cad = payload.trip.available_funds_amount
        value.trip.estimated_spend_currency = payload.trip.available_funds_currency
        value.trip.funds_source_reference = payload.trip.funds_source_reference
        primary_funding = next((item for item in payload.funding if item.is_primary), None)
        if primary_funding:
            value.trip.payer = primary_funding.payer_kind
            value.trip.payer_details = primary_funding.description or primary_funding.party_name or ""
        primary_host = next((item for item in payload.hosts if item.is_primary), None)
        if primary_host:
            value.trip.visiting_person_or_institution = primary_host.host_type
            value.trip.host_name = primary_host.display_name
            value.trip.relationship = primary_host.relationship_to_applicant or ""
            value.trip.family_relationship = primary_host.family_relationship or ""
            value.trip.host_status = primary_host.immigration_status_in_canada or ""
            value.trip.host_address = _address_line(primary_host.address) if primary_host.address else ""
            value.trip.host_phone = primary_host.phone or ""
            value.trip.host_email = primary_host.email or ""

        primary_education = next((item for item in payload.education if item.is_primary), None)
        if primary_education:
            value.education.level = primary_education.level or ""
            value.education.institution = primary_education.institution_name or ""
            value.education.course = primary_education.course or ""
            value.education.start_date = primary_education.start_date.isoformat() if primary_education.start_date else ""
            value.education.end_date = primary_education.end_date.isoformat() if primary_education.end_date else ""
            value.education.country = primary_education.country_code or ""
            value.education.city = primary_education.city or ""
            value.education.state = primary_education.state_province or ""
            value.education.post_secondary_details = primary_education.details or ""

        value.activities = [Activity(
            id=f"canonical-{index + 1}", status=item.period_status,
            activity_type=item.activity_type or "", start_date=item.start_date.isoformat() if item.start_date else "",
            end_date=item.end_date.isoformat() if item.end_date else "", position=item.position or "",
            organization=item.organization_name or "", description=item.duties or "",
            city=item.city or "", state=item.state_province or "", country=item.country_code or "",
            ongoing_answer="Yes" if item.period_status == "current" else "No",
            source_block_index=index + 1, source_role="canonical",
        ) for index, item in enumerate(payload.activities)]
        current_activity = next((item for item in payload.activities if item.period_status == "current"), None)
        if current_activity:
            value.employment.profession = current_activity.position or ""
            value.employment.organization = current_activity.organization_name or ""
            value.employment.duties = current_activity.duties or ""
            value.employment.start_date = current_activity.start_date.isoformat() if current_activity.start_date else ""
            value.employment.city = current_activity.city or ""
            value.employment.state = current_activity.state_province or ""

        spouse = next((item for item in payload.family if item.relationship_type == "spouse" and item.is_current), None)
        former = [item for item in payload.family if item.relationship_type == "former_spouse"]
        if spouse: _map_spouse(value, spouse, former=False)
        if former: _map_spouse(value, former[0], former=True)
        parents = [item for item in payload.family if item.relationship_type == "parent"]
        children = [item for item in payload.family if item.relationship_type == "child"]
        value.family.parents = [_family_member(item) for item in parents]
        value.family.children = [_family_member(item) for item in children]
        value.family.has_children_answer = "Yes" if children else "No"

        value.residence_records = [_history(item.country_code, item.status_or_purpose, item.start_date, item.end_date, "residence") for item in payload.residence_history]
        value.travel_records = [_history(item.country_code, item.purpose, item.entry_date, item.exit_date, "travel") for item in payload.travel_history]
        answers = {item.question_code: item.answer for item in payload.official_answers}
        for code, answer in answers.items(): setattr(value.official_review, code, _answer(answer))
        for explanation in payload.official_explanations: setattr(value.official_review, explanation.section_code, explanation.text)

        rep = payload.representative
        for target, source in (("family_name", "family_name"), ("given_names", "given_names"),
                               ("organization", "organization_name"), ("unit", "unit"),
                               ("street_number", "street_number"), ("street_name", "street_name"),
                               ("city", "city"), ("province", "province"), ("country", "country_code"),
                               ("postcode", "postal_code"), ("phone_country_code", "phone_country_code"),
                               ("phone_number", "phone_number"), ("email", "email"), ("action", "action"),
                               ("category", "category"), ("membership_number", "membership_number"),
                               ("membership_province", "membership_province"), ("other_category_details", "other_category_details"),
                               ("supervising_lawyer", "supervising_lawyer"), ("supervising_lawyer_membership", "supervising_lawyer_membership"),
                               ("cancelled_family_name", "cancelled_representative_family_name"),
                               ("cancelled_given_names", "cancelled_representative_given_names"),
                               ("cancelled_organization", "cancelled_organization_name")):
            setattr(value.representative, target, getattr(rep, source) or "")
        return value


def _language(value: str | None) -> str:
    return {"en": "English", "eng": "English", "fr": "French", "fra": "French", "pt": "Portuguese", "por": "Portuguese"}.get((value or "").casefold(), value or "")


def _answer(value: str) -> str:
    if value not in {"yes", "no"}:
        raise ValueError("current official form accepts only explicit yes/no answers")
    return "Yes" if value == "yes" else "No"


def _address_line(item) -> str:
    return " ".join(str(value).strip() for value in (item.unit, item.street_number, item.street_name, item.city, item.state_province, item.postal_code, item.country_code) if value)


def _family_member(item) -> FamilyMember:
    person = item.related_person
    return FamilyMember(
        confirmed_role=item.parent_type or "", source_role="canonical", source_block_index=item.sort_order + 1,
        relationship=item.relationship_type, family_name=person.family_name, given_names=person.given_names,
        date_of_birth=person.date_of_birth.isoformat() if person.date_of_birth else "",
        birth_country=person.birth_country_code or "", marital_status=person.marital_status or "",
        occupation=person.occupation_text or "", address=_address_line(item.address) if item.address else "",
        death_details=item.death_details or "", accompanying_answer=("Yes" if item.accompanying_applicant else "No") if item.accompanying_applicant is not None else "",
    )


def _map_spouse(case: CanadaCase, item, *, former: bool) -> None:
    person = item.related_person
    if former:
        case.relationships.has_previous_relationship = "Yes"
        case.relationships.former_spouse_family_name = person.family_name
        case.relationships.former_spouse_given_names = person.given_names
        case.relationships.former_spouse_birth_country = person.birth_country_code or ""
        case.relationships.former_spouse_date_of_birth = person.date_of_birth.isoformat() if person.date_of_birth else ""
        case.relationships.previous_relationship_type = item.previous_relationship_type or item.relationship_type
        case.relationships.previous_start_date = item.relationship_start_date.isoformat() if item.relationship_start_date else ""
        case.relationships.previous_end_date = item.relationship_end_date.isoformat() if item.relationship_end_date else ""
    else:
        case.relationships.spouse_family_name = person.family_name
        case.relationships.spouse_given_names = person.given_names
        case.relationships.spouse_birth_country = person.birth_country_code or ""
        case.relationships.spouse_date_of_birth = person.date_of_birth.isoformat() if person.date_of_birth else ""
        case.relationships.spouse_occupation = person.occupation_text or ""
        case.relationships.spouse_address = _address_line(item.address) if item.address else ""
        case.relationships.spouse_accompanying_answer = ("Yes" if item.accompanying_applicant else "No") if item.accompanying_applicant is not None else ""
        case.relationships.marriage_start_date = item.relationship_start_date.isoformat() if item.relationship_start_date else ""


def _history(country: str, purpose: str, start, end, role: str) -> HistoryRecord:
    record = HistoryRecord(country=country, status_or_purpose=purpose, start_date=start.isoformat(), end_date=end.isoformat(), source_role=role)
    record.confirmation_digest = record_digest(record)
    return record
