from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config.canada_preparation_policy import (
    OFFICIAL_EXPLANATION_CONDITIONS,
    OFFICIAL_QUESTION_CODES,
    PAYLOAD_PROJECTIONS,
    PAYLOAD_SCHEMA_VERSION,
    POLICY_VERSION,
    REPRESENTATIVE_ACTIONS,
    REPRESENTATIVE_CATEGORIES,
    REPRESENTATIVE_LAW_SOCIETY_CATEGORIES,
    REPRESENTATIVE_MEMBERSHIP_CATEGORIES,
)
from ..models import canada as cm
from ..schemas import canada_preparation as ps
from .core import DomainNotFound, DomainValidationError


REVIEWED = frozenset({cm.ReviewState.CONFIRMED.value, cm.ReviewState.CORRECTED.value})
RELEVANT_FACT_KEYS = ("sponsor.exists", "host.exists", "trip.payer")
PREPARATION_LEGACY_PATHS = frozenset(item.legacy_path for item in PAYLOAD_PROJECTIONS)

SECTION_LABELS = {
    "application": "Application", "applicant": "Applicant", "passport": "Passport",
    "contact": "Contact and addresses", "trip": "Trip", "host": "Host",
    "funding": "Funding", "family": "Family", "education": "Education",
    "activities": "Activities", "history": "Residence and travel history",
    "official_answers": "Official questions", "representative": "Representative",
    "imports": "Imported data", "facts": "Case facts", "documents": "Documents",
}


def canonical_payload_bytes(payload: ps.CanonicalPreparationPayload) -> bytes:
    """Serialize only semantic payload data with stable JSON rules."""
    value = payload.model_dump(mode="json")
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_payload_hash(payload: ps.CanonicalPreparationPayload) -> str:
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


class CanadaPreparationReadinessService:
    """Evaluates the internal preparation standard using canonical state only."""

    def __init__(self, session: Session):
        self.session = session
        self._issues: list[ps.PreparationIssue] = []

    def evaluate(self, case_id: uuid.UUID) -> ps.PreparationReadinessResult:
        self._issues = []
        case = self.session.get(models.Case, case_id)
        if case is None:
            raise DomainNotFound("Case not found")
        app = self.session.scalar(select(cm.CanadaApplication).where(cm.CanadaApplication.case_id == case_id))
        if app is None:
            self._issue("missing_selection", "application", "applicant", "Canada application",
                        "Initialize the canonical Canada application and select its applicant.")
            return self._result(None)

        applicant = self._applicant(case_id, app)
        biography = self.session.get(cm.PersonBiography, applicant.id) if applicant else None
        self._applicant_values(applicant, biography)

        citizenships = list(self.session.scalars(select(cm.PersonCitizenship).where(
            cm.PersonCitizenship.person_id == app.applicant_person_id
        ).order_by(cm.PersonCitizenship.sort_order))) if applicant else []
        if len([item for item in citizenships if item.is_primary]) != 1:
            self._issue("missing_selection", "applicant.citizenship.primary", "applicant", "Primary citizenship",
                        "Select exactly one primary citizenship.")

        residences = list(self.session.scalars(select(cm.ApplicantResidence).where(
            cm.ApplicantResidence.application_id == app.id
        )))
        current_residences = [item for item in residences if item.is_current]
        if len(current_residences) != 1:
            self._issue("invalid_cardinality", "applicant.current_residence", "contact", "Current residence",
                        "Select exactly one current country of residence.")
        elif not current_residences[0].country_code:
            self._missing("applicant.current_residence.country_code", "contact", "Current residence country")

        passports = list(self.session.scalars(select(cm.TravelDocument).where(
            cm.TravelDocument.application_id == app.id,
            cm.TravelDocument.document_type == "passport",
        ).order_by(cm.TravelDocument.sort_order)))
        primary_passports = [item for item in passports if item.is_primary]
        passport = primary_passports[0] if len(primary_passports) == 1 else None
        if len(primary_passports) != 1:
            self._issue("missing_selection" if not primary_passports else "invalid_cardinality",
                        "applicant.passport.primary", "passport", "Primary passport",
                        "Select exactly one primary passport for the applicant.")
        if passport:
            if passport.person_id != app.applicant_person_id:
                self._issue("inconsistent_data", "applicant.passport.primary", "passport", "Primary passport owner",
                            "Assign the primary passport to the explicitly selected applicant.")
            for field, label in (("number", "Passport number"), ("issuing_country_code", "Issuing country"),
                                 ("issue_date", "Passport issue date"), ("expiry_date", "Passport expiry date")):
                if not getattr(passport, field): self._missing(f"applicant.passport.{field}", "passport", label)
                else: self._derived_review(case_id, "travel_document", passport.id, field,
                                           f"applicant.passport.{field}", "passport", label)
            if app.official_application_date and passport.expiry_date and passport.expiry_date < app.official_application_date:
                self._issue("unsupported_value", "applicant.passport.expiry_date", "passport", "Passport validity",
                            "Select a primary passport valid on the intended application package date.")
            valid_secondary = [item for item in passports if item.person_id == app.applicant_person_id and
                               not item.is_primary and item.expiry_date and
                               app.official_application_date and item.expiry_date >= app.official_application_date]
            if passport.details and not valid_secondary:
                self._issue("ambiguous_reference", "applicant.passport.secondary", "passport", "Other valid passport",
                            "Create an explicit secondary passport record; legacy free text alone cannot establish another valid passport.")

        contacts = list(self.session.scalars(select(cm.ContactPoint).where(
            cm.ContactPoint.person_id == app.applicant_person_id
        ).order_by(cm.ContactPoint.sort_order, cm.ContactPoint.type))) if applicant else []
        for kind, label in (("email", "Primary email"), ("phone", "Primary phone")):
            selected = [item for item in contacts if item.type == kind and item.is_primary]
            if len(selected) != 1:
                self._issue("missing_selection" if not selected else "invalid_cardinality",
                            f"applicant.contact.{kind}", "contact", label,
                            f"Select exactly one primary {kind} contact.")

        addresses = list(self.session.scalars(select(cm.Address).where(cm.Address.application_id == app.id)))
        residential = [item for item in addresses if item.context == cm.AddressContext.RESIDENTIAL and item.owner_id == app.id]
        if len(residential) != 1:
            self._issue("missing_selection" if not residential else "invalid_cardinality",
                        "applicant.residential_address", "contact", "Residential address",
                        "Maintain exactly one application-owned residential address.")
        else:
            self._address_ready(residential[0], "applicant.residential_address", "Residential address")
        mailing = [item for item in addresses if item.context == cm.AddressContext.MAILING and item.owner_id == app.id]
        if app.mailing_same_as_residential is None:
            self._issue("missing_selection", "application.mailing_same_as_residential", "contact", "Mailing-address choice",
                        "Confirm whether the mailing address is the same as the residential address.")
        elif app.mailing_same_as_residential is False:
            if len(mailing) != 1:
                self._issue("missing_selection" if not mailing else "invalid_cardinality",
                            "applicant.mailing_address", "contact", "Mailing address",
                            "Maintain exactly one mailing address when it differs from the residential address.")
            else:
                self._address_ready(mailing[0], "applicant.mailing_address", "Mailing address")

        if not app.official_application_date:
            self._missing("application.official_application_date", "application", "Official application package date")
        elif app.application_date_review_state not in REVIEWED:
            self._review("application.official_application_date", "application", "Official application package date")

        trip = self.session.scalar(select(cm.TripPlan).where(cm.TripPlan.application_id == app.id))
        self._trip_ready(trip)
        facts = self._facts(case_id)
        self._fact_conflicts(case_id)

        hosts = list(self.session.scalars(select(cm.HostRecord).where(
            cm.HostRecord.trip_plan_id == trip.id
        ).order_by(cm.HostRecord.sort_order))) if trip else []
        funding = list(self.session.scalars(select(cm.FundingSource).where(
            cm.FundingSource.trip_plan_id == trip.id
        ).order_by(cm.FundingSource.sort_order))) if trip else []
        self._host_ready(facts.get("host.exists"), hosts)
        self._funding_ready(case_id, facts, funding)

        activities = list(self.session.scalars(select(cm.ActivityRecord).where(
            cm.ActivityRecord.application_id == app.id,
            cm.ActivityRecord.person_id == app.applicant_person_id,
        ).order_by(cm.ActivityRecord.sort_order)))
        if not activities:
            self._issue("missing_collection_record", "activities", "activities", "Applicant activity history",
                        "Add at least one applicant activity record used by the supported forms.")
        for index, activity in enumerate(activities):
            if activity.period_status == "unknown":
                self._issue("review_required", f"activities[{index}].period_status", "activities", "Activity period status",
                            "Confirm whether the activity is current or completed.")
            if not activity.start_date or not activity.position:
                self._issue("incomplete_collection", f"activities[{index}]", "activities", "Activity record",
                            "Complete the activity start date and position/occupation.")

        relationships = list(self.session.scalars(select(cm.FamilyRelationship).where(
            cm.FamilyRelationship.application_id == app.id
        ).order_by(cm.FamilyRelationship.relationship_type, cm.FamilyRelationship.sort_order)))
        current_spouses = [item for item in relationships if item.relationship_type == "spouse" and item.is_current]
        if len(current_spouses) > 1:
            self._issue("invalid_cardinality", "family.current_spouse", "family", "Current spouse",
                        "Only one current spouse may be selected.")
        former_spouses = [item for item in relationships if item.relationship_type == "former_spouse"]
        if len(former_spouses) > 1:
            self._issue("invalid_cardinality", "family.former_spouse", "family", "Former spouse",
                        "The current form supports one former-spouse record; resolve which reviewed record belongs in this package.")
        parents = [item for item in relationships if item.relationship_type == "parent"]
        if len(parents) > 2:
            self._issue("invalid_cardinality", "family.parents", "family", "Parents",
                        "The current family form supports at most two parent records.")

        answers = {item.question_code: item for item in self.session.scalars(select(cm.OfficialApplicationAnswer).where(
            cm.OfficialApplicationAnswer.application_id == app.id
        ))}
        self._official_ready(app.id, answers)

        education = list(self.session.scalars(select(cm.EducationRecord).where(
            cm.EducationRecord.application_id == app.id,
            cm.EducationRecord.person_id == app.applicant_person_id,
        ).order_by(cm.EducationRecord.sort_order)))
        post_secondary = answers.get("post_secondary_education")
        if post_secondary and post_secondary.answer == cm.OfficialAnswerValue.YES:
            primary = [item for item in education if item.is_primary]
            if len(primary) != 1:
                self._issue("missing_selection" if not primary else "invalid_cardinality",
                            "education.primary", "education", "Primary post-secondary education",
                            "Select exactly one primary education record for the confirmed post-secondary branch.")
            elif any(not getattr(primary[0], field) for field in ("institution_name", "start_date", "city", "state_province", "country_code")):
                self._issue("incomplete_collection", "education.primary", "education", "Primary education record",
                            "Complete institution, start date, city, state/province, and country.")

        for model, path, label in (
            (cm.ResidenceHistoryRecord, "residence_history", "Residence history"),
            (cm.TravelHistoryRecord, "travel_history", "Travel history"),
        ):
            for index, record in enumerate(self.session.scalars(select(model).where(
                model.application_id == app.id,
                model.person_id == app.applicant_person_id,
            ).order_by(model.sort_order))):
                if record.review_state not in REVIEWED:
                    self._review(f"{path}[{index}]", "history", label)

        self._representative_ready(case_id, app)
        self._import_conflicts(case_id)
        self._blocking_requirements(case_id)

        if self._issues:
            return self._result(None)
        payload = CanonicalPreparationPayloadBuilder(self.session)._build(case_id)
        return self._result(canonical_payload_hash(payload))

    def _applicant(self, case_id, app):
        roles = list(self.session.scalars(select(cm.CasePersonRole).where(
            cm.CasePersonRole.case_id == case_id,
            cm.CasePersonRole.role == cm.OperationalRole.APPLICANT,
        )))
        if app.applicant_person_id is None:
            self._issue("missing_selection", "application.applicant", "applicant", "Selected applicant",
                        "Select the applicant explicitly.")
            return None
        applicant = self.session.get(models.Person, app.applicant_person_id)
        if applicant is None or applicant.case_id != case_id:
            self._issue("ambiguous_reference", "application.applicant", "applicant", "Selected applicant",
                        "Repair the applicant reference so it points to a person in this case.")
            return None
        if len(roles) != 1 or roles[0].person_id != applicant.id:
            self._issue("invalid_cardinality", "application.applicant", "applicant", "Selected applicant",
                        "The application and operational applicant role must identify exactly the same one person.")
        return applicant

    def _applicant_values(self, applicant, biography):
        if applicant is None: return
        if not applicant.last_name.strip(): self._missing("applicant.family_name", "applicant", "Family name")
        if not applicant.first_name.strip(): self._missing("applicant.given_names", "applicant", "Given names")
        fields = (("date_of_birth", "Date of birth"), ("sex", "Sex"), ("birth_city", "City of birth"),
                  ("birth_country_code", "Country of birth"), ("marital_status", "Marital status"))
        for field, label in fields:
            if biography is None or not getattr(biography, field):
                self._missing(f"applicant.biography.{field}", "applicant", label)

    def _address_ready(self, address, path, label):
        for field, field_label in (("street_name", "street name"), ("city", "city"),
                                   ("state_province", "state/province"), ("postal_code", "postal code"),
                                   ("country_code", "country")):
            if not getattr(address, field):
                self._issue("missing_value", f"{path}.{field}", "contact", f"{label} {field_label}",
                            f"Complete the structured {field_label}; unstructured address text is not a preparation fallback.")
        if address.review_state not in REVIEWED:
            self._review(path, "contact", label)

    def _trip_ready(self, trip):
        if trip is None:
            self._issue("missing_collection_record", "trip", "trip", "Trip plan", "Create the canonical trip plan.")
            return
        for field, label in (("intake_purpose_text", "Travel purpose"), ("imm5257_purpose_code", "IMM5257 purpose"),
                             ("arrival_date", "Arrival date"), ("departure_date", "Departure date"),
                             ("available_funds_amount", "Available funds"), ("available_funds_currency", "Funds currency"),
                             ("funds_source_reference", "Funds source")):
            if getattr(trip, field) is None or getattr(trip, field) == "": self._missing(f"trip.{field}", "trip" if "fund" not in field else "funding", label)
        if trip.imm5257_purpose_code and trip.purpose_review_state not in REVIEWED:
            self._review("trip.imm5257_purpose_code", "trip", "IMM5257 purpose")

    def _facts(self, case_id):
        result = {}
        for key in RELEVANT_FACT_KEYS:
            value = self.session.scalar(select(models.Fact).where(
                models.Fact.case_id == case_id, models.Fact.key == key, models.Fact.status == "confirmed"
            ).order_by(models.Fact.created_at.desc(), models.Fact.id.desc()).limit(1))
            result[key] = value.value_json if value else None
            if value is None:
                self._issue("missing_selection", f"facts.{key}", "facts", key,
                            f"Confirm {key} before preparation.")
        return result

    def _fact_conflicts(self, case_id):
        for fact in self.session.scalars(select(models.Fact).where(
            models.Fact.case_id == case_id, models.Fact.key.in_(RELEVANT_FACT_KEYS), models.Fact.status == "conflict"
        ).order_by(models.Fact.created_at, models.Fact.id)):
            self._issue("unresolved_fact_conflict", f"facts.{fact.key}", "facts", fact.key,
                        "Resolve the conflicting case fact; readiness never chooses a value automatically.")

    def _host_ready(self, host_exists, hosts):
        primary = [item for item in hosts if item.is_primary]
        if host_exists is True and len(primary) != 1:
            self._issue("missing_selection" if not primary else "invalid_cardinality", "host.primary", "host", "Primary host",
                        "Select exactly one primary host because host.exists is confirmed true.")
        if host_exists is False and primary:
            self._issue("inconsistent_data", "host.primary", "host", "Host contradiction",
                        "Remove or resolve the primary host because host.exists is confirmed false.")
        if len(primary) == 1:
            host = primary[0]
            party = self.session.get(models.Person, host.person_id) if host.person_id else self.session.get(cm.Organization, host.organization_id)
            if party is None:
                self._issue("ambiguous_reference", "host.primary.party", "host", "Primary host party",
                            "Repair the selected host person or organization reference.")

    def _funding_ready(self, case_id, facts, funding):
        sponsor_exists, payer = facts.get("sponsor.exists"), facts.get("trip.payer")
        primary = [item for item in funding if item.is_primary]
        sponsor_roles = list(self.session.scalars(select(cm.CasePersonRole).where(
            cm.CasePersonRole.case_id == case_id,
            cm.CasePersonRole.role == cm.OperationalRole.SPONSOR,
        )))
        if sponsor_exists is True and len(sponsor_roles) != 1:
            self._issue("missing_selection" if not sponsor_roles else "invalid_cardinality",
                        "funding.sponsor_person", "funding", "Sponsor person",
                        "Select exactly one sponsor PERSON because sponsor.exists is confirmed true.")
        if sponsor_exists is False and sponsor_roles:
            self._issue("inconsistent_data", "funding.sponsor_person", "funding", "Sponsor contradiction",
                        "Remove or resolve the sponsor role because sponsor.exists is confirmed false.")
        if sponsor_exists is True and len(primary) != 1:
            self._issue("missing_selection" if not primary else "invalid_cardinality", "funding.primary", "funding", "Primary funding source",
                        "Select exactly one primary funding source because sponsor.exists is confirmed true.")
        if sponsor_exists is False and any(item.payer_kind not in {"applicant", "self"} for item in primary):
            self._issue("inconsistent_data", "funding.primary", "funding", "Sponsor contradiction",
                        "Resolve the non-applicant funding source because sponsor.exists is confirmed false.")
        if len(primary) == 1 and payer:
            normalized_fact = "applicant" if payer == "self" else payer
            normalized_source = "applicant" if primary[0].payer_kind == "self" else primary[0].payer_kind
            if normalized_fact != normalized_source:
                self._issue("inconsistent_data", "funding.primary.payer_kind", "funding", "Trip payer",
                            "Resolve the confirmed trip.payer FACT and primary funding source so they identify the same payer kind.")
        if len(primary) == 1 and primary[0].person_id and sponsor_roles and primary[0].payer_kind == "sponsor":
            if primary[0].person_id != sponsor_roles[0].person_id:
                self._issue("ambiguous_reference", "funding.primary.person", "funding", "Primary sponsor",
                            "Select the same sponsor PERSON in the role and primary funding source.")
        if sponsor_exists is True and payer in {"applicant", "self"} and primary and not primary[0].description:
            self._issue("ambiguous_reference", "funding.primary.description", "funding", "Mixed funding explanation",
                        "Describe the reviewed mixed-funding arrangement instead of normalizing it automatically.")

    def _official_ready(self, application_id, answers):
        for code in OFFICIAL_QUESTION_CODES:
            answer = answers.get(code)
            if answer is None:
                self._missing(f"official_answers.{code}", "official_answers", code.replace("_", " ").title())
            elif answer.answer == cm.OfficialAnswerValue.UNKNOWN:
                self._issue("unsupported_value", f"official_answers.{code}", "official_answers", code.replace("_", " ").title(),
                            "Choose yes, no, or not applicable; unknown never counts as no.")
            elif answer.answer == cm.OfficialAnswerValue.NOT_APPLICABLE:
                self._issue("unsupported_value", f"official_answers.{code}", "official_answers", code.replace("_", " ").title(),
                            "The current binary official-form control cannot represent not applicable; confirm Yes or No for this package.")
            elif answer.review_state not in REVIEWED:
                self._review(f"official_answers.{code}", "official_answers", code.replace("_", " ").title())
        explanations = {item.section_code: item for item in self.session.scalars(select(cm.OfficialExplanation).where(
            cm.OfficialExplanation.application_id == application_id
        ))}
        for section, question_codes in OFFICIAL_EXPLANATION_CONDITIONS.items():
            if any(answers.get(code) and answers[code].answer == cm.OfficialAnswerValue.YES for code in question_codes):
                explanation = explanations.get(section)
                if explanation is None or not explanation.text.strip():
                    self._missing(f"official_explanations.{section}", "official_answers", section.replace("_", " ").title())
                elif explanation.review_state not in REVIEWED:
                    self._review(f"official_explanations.{section}", "official_answers", section.replace("_", " ").title())

    def _representative_ready(self, case_id, app):
        authorization = self.session.scalar(select(cm.RepresentativeAuthorization).where(
            cm.RepresentativeAuthorization.application_id == app.id
        ))
        if authorization is None:
            self._issue("missing_selection", "representative.authorization", "representative", "Representative authorization",
                        "Select the representative person and immutable profile revision.")
            return
        role = self.session.scalar(select(cm.CasePersonRole).where(
            cm.CasePersonRole.case_id == case_id,
            cm.CasePersonRole.person_id == authorization.representative_person_id,
            cm.CasePersonRole.role == cm.OperationalRole.REPRESENTATIVE,
        ))
        if role is None:
            self._issue("ambiguous_reference", "representative.person", "representative", "Representative person",
                        "Assign the representative operational role to the selected person.")
        revision = self.session.get(cm.RepresentativeProfileRevision, authorization.profile_revision_id)
        if revision is None:
            self._issue("ambiguous_reference", "representative.profile_revision", "representative", "Representative profile revision",
                        "Select an existing immutable representative profile revision.")
            return
        if authorization.review_state not in REVIEWED:
            self._review("representative.authorization", "representative", "Representative authorization")
        if authorization.action not in REPRESENTATIVE_ACTIONS:
            self._issue("unsupported_value", "representative.action", "representative", "Representative action",
                        "Select a supported appointment, update, cancellation, or withdrawal action.")
        for field, label in (("family_name", "Family name"), ("given_names", "Given names"),
                             ("street_name", "Street name"), ("city", "City"), ("province", "Province"),
                             ("country_code", "Country"), ("postal_code", "Postal code"),
                             ("phone_number", "Phone number"), ("email", "Email"), ("category", "Category")):
            if not getattr(revision, field): self._missing(f"representative.{field}", "representative", f"Representative {label.lower()}")
        if revision.category and revision.category not in REPRESENTATIVE_CATEGORIES:
            self._issue("unsupported_value", "representative.category", "representative", "Representative category",
                        "Select a category supported by the current representative form mapping.")
        if revision.category in REPRESENTATIVE_MEMBERSHIP_CATEGORIES and not revision.membership_number:
            self._missing("representative.membership_number", "representative", "Representative membership number")
        if revision.category == "Unpaid - other" and not revision.other_category_details:
            self._missing("representative.other_category_details", "representative", "Other representative category details")
        if revision.category in REPRESENTATIVE_LAW_SOCIETY_CATEGORIES:
            for field, label in (("membership_province", "Membership province"),
                                 ("supervising_lawyer", "Supervising lawyer"),
                                 ("supervising_lawyer_membership", "Supervising lawyer membership")):
                if not getattr(revision, field): self._missing(f"representative.{field}", "representative", label)

    def _import_conflicts(self, case_id):
        for candidate in self.session.scalars(select(cm.CanadaImportCandidate).join(
            cm.CanadaLegacyImportRun, cm.CanadaLegacyImportRun.id == cm.CanadaImportCandidate.import_run_id
        ).where(
            cm.CanadaLegacyImportRun.case_id == case_id,
            cm.CanadaImportCandidate.status.in_(("conflict", "ambiguous")),
            cm.CanadaImportCandidate.source_path.in_(PREPARATION_LEGACY_PATHS),
        ).order_by(cm.CanadaImportCandidate.created_at, cm.CanadaImportCandidate.id)):
            self._issue("unresolved_import_conflict", f"imports.{candidate.source_path}", "imports", candidate.employee_label,
                        "Resolve this preparation-relevant import difference before preparing forms.")

    def _blocking_requirements(self, case_id):
        for requirement in self.session.scalars(select(models.Requirement).where(
            models.Requirement.case_id == case_id,
            models.Requirement.active.is_(True),
            models.Requirement.is_blocking.is_(True),
            models.Requirement.fulfillment_status == models.RequirementFulfillmentStatus.PENDING,
        ).order_by(models.Requirement.created_at, models.Requirement.id)):
            self._issue("blocking_requirement", f"requirements.{requirement.document_type}", "documents", requirement.document_type,
                        "Fulfil or explicitly waive the active blocking requirement through the existing document workflow.")

    def _derived_review(self, case_id, entity_type, entity_id, field, path, section, label):
        provenance = self.session.scalar(select(cm.FieldProvenanceReview).where(
            cm.FieldProvenanceReview.case_id == case_id,
            cm.FieldProvenanceReview.entity_type == entity_type,
            cm.FieldProvenanceReview.entity_id == entity_id,
            cm.FieldProvenanceReview.field_key == field,
            cm.FieldProvenanceReview.superseded_at.is_(None),
        ).order_by(cm.FieldProvenanceReview.created_at.desc(), cm.FieldProvenanceReview.id.desc()).limit(1))
        if provenance and provenance.source_type in {"legacy_derived", "legacy_narrative_derived", "legacy_staff_review"} and provenance.review_state not in REVIEWED:
            self._review(path, section, label)

    def _missing(self, path, section, label):
        self._issue("missing_value", path, section, label, f"Enter {label.lower()} before preparation.")

    def _review(self, path, section, label):
        self._issue("review_required", path, section, label, f"An employee must confirm or correct {label.lower()} before preparation.")

    def _issue(self, code, path, section, label, message, *, severity="blocking"):
        key = (code, path)
        if any((item.code, item.path) == key for item in self._issues): return
        self._issues.append(ps.PreparationIssue(
            code=code, path=path, section=section, label=label,
            severity=severity, blocking=severity == "blocking", message=message,
            action=self._action(section),
        ))

    @staticmethod
    def _action(section):
        return {
            "imports":"Review Canada import changes", "facts":"Resolve the case fact",
            "documents":"Open document requirements",
        }.get(section, f"Open the {SECTION_LABELS.get(section, section)} section")

    def _result(self, payload_hash):
        blockers = tuple(item for item in self._issues if item.blocking)
        warnings = tuple(item for item in self._issues if not item.blocking)
        grouped = defaultdict(list)
        for item in self._issues: grouped[item.section].append(item)
        sections = tuple(ps.PreparationSection(
            section=section, label=SECTION_LABELS.get(section, section.replace("_", " ").title()),
            blocking_count=sum(item.blocking for item in items),
            warning_count=sum(not item.blocking for item in items), issues=tuple(items),
        ) for section, items in grouped.items())
        return ps.PreparationReadinessResult(
            ready=not blockers, policy_version=POLICY_VERSION,
            schema_version=PAYLOAD_SCHEMA_VERSION, payload_hash=payload_hash,
            issues=blockers, warnings=warnings, sections=sections,
            blocking_count=len(blockers), warning_count=len(warnings),
        )


class CanonicalPreparationPayloadBuilder:
    """Builds a detached immutable semantic snapshot after readiness succeeds."""

    def __init__(self, session: Session): self.session = session

    def build(self, case_id: uuid.UUID) -> ps.CanonicalPreparationPayload:
        readiness = CanadaPreparationReadinessService(self.session).evaluate(case_id)
        if not readiness.ready:
            raise DomainValidationError("canonical Canada application is not preparation-ready")
        return self._build(case_id)

    def _build(self, case_id: uuid.UUID) -> ps.CanonicalPreparationPayload:
        app = self.session.scalar(select(cm.CanadaApplication).where(cm.CanadaApplication.case_id == case_id))
        if app is None or app.applicant_person_id is None: raise DomainValidationError("applicant is not selected")
        person = self.session.get(models.Person, app.applicant_person_id)
        biography = self.session.get(cm.PersonBiography, person.id)
        passport = self.session.scalar(select(cm.TravelDocument).where(
            cm.TravelDocument.application_id == app.id, cm.TravelDocument.is_primary.is_(True)
        ))
        secondary_passports = tuple(self.session.scalars(select(cm.TravelDocument).where(
            cm.TravelDocument.application_id == app.id,
            cm.TravelDocument.person_id == person.id,
            cm.TravelDocument.document_type == "passport",
            cm.TravelDocument.is_primary.is_(False),
            cm.TravelDocument.expiry_date >= app.official_application_date,
        ).order_by(cm.TravelDocument.sort_order)))
        trip = self.session.scalar(select(cm.TripPlan).where(cm.TripPlan.application_id == app.id))
        residential = self.session.scalar(select(cm.Address).where(
            cm.Address.application_id == app.id, cm.Address.context == "residential", cm.Address.owner_id == app.id
        ))
        mailing = self.session.scalar(select(cm.Address).where(
            cm.Address.application_id == app.id, cm.Address.context == "mailing", cm.Address.owner_id == app.id
        ))
        authorization = self.session.scalar(select(cm.RepresentativeAuthorization).where(cm.RepresentativeAuthorization.application_id == app.id))
        revision = self.session.get(cm.RepresentativeProfileRevision, authorization.profile_revision_id)

        contacts = tuple(ps.ContactPayload(
            type=item.type, value=item.value, country_code=item.country_code, purpose=item.purpose,
            is_primary=item.is_primary, sort_order=item.sort_order,
        ) for item in self.session.scalars(select(cm.ContactPoint).where(
            cm.ContactPoint.person_id == person.id
        ).order_by(cm.ContactPoint.sort_order, cm.ContactPoint.type, cm.ContactPoint.value)))
        residences = tuple(ps.ResidencePayload(
            country_code=item.country_code, immigration_status_code=item.immigration_status_code,
            resident_since=item.resident_since, is_current=item.is_current,
        ) for item in self.session.scalars(select(cm.ApplicantResidence).where(
            cm.ApplicantResidence.application_id == app.id
        ).order_by(cm.ApplicantResidence.is_current.desc(), cm.ApplicantResidence.country_code)))
        hosts = tuple(self._host(item) for item in self.session.scalars(select(cm.HostRecord).where(
            cm.HostRecord.trip_plan_id == trip.id
        ).order_by(cm.HostRecord.sort_order)))
        funding = tuple(self._funding(item) for item in self.session.scalars(select(cm.FundingSource).where(
            cm.FundingSource.trip_plan_id == trip.id
        ).order_by(cm.FundingSource.sort_order)))
        family = tuple(self._family(item) for item in self.session.scalars(select(cm.FamilyRelationship).where(
            cm.FamilyRelationship.application_id == app.id
        ).order_by(cm.FamilyRelationship.relationship_type, cm.FamilyRelationship.sort_order)))

        cancelled = self.session.get(models.Person, authorization.cancelled_representative_person_id) if authorization.cancelled_representative_person_id else None
        return ps.CanonicalPreparationPayload(
            schema_version=PAYLOAD_SCHEMA_VERSION, policy_version=POLICY_VERSION,
            application=ps.ApplicationPayload(
                official_application_date=app.official_application_date,
                native_language_code=app.native_language_code,
                preferred_language_code=app.preferred_language_code,
                service_language_code=app.service_language_code,
                mailing_same_as_residential=app.mailing_same_as_residential,
            ),
            applicant=ps.ApplicantPayload(
                family_name=person.last_name, given_names=person.first_name,
                display_name=self._display_name(person),
                biography=ps.BiographyPayload(
                    date_of_birth=biography.date_of_birth, other_names=biography.other_names,
                    sex=biography.sex, birth_city=biography.birth_city,
                    birth_state_province=biography.birth_state_province,
                    birth_country_code=biography.birth_country_code,
                    marital_status=biography.marital_status,
                ),
                citizenships=tuple(ps.CitizenshipPayload(
                    country_code=item.country_code, citizenship_type=item.citizenship_type,
                    is_primary=item.is_primary, sort_order=item.sort_order,
                ) for item in self.session.scalars(select(cm.PersonCitizenship).where(
                    cm.PersonCitizenship.person_id == person.id
                ).order_by(cm.PersonCitizenship.sort_order))),
                identifiers=tuple(ps.IdentifierPayload(
                    identifier_type=item.identifier_type, country_code=item.country_code,
                    value=item.value, issue_date=item.issue_date, expiry_date=item.expiry_date,
                ) for item in self.session.scalars(select(cm.PersonIdentifier).where(
                    cm.PersonIdentifier.person_id == person.id
                ).order_by(cm.PersonIdentifier.identifier_type, cm.PersonIdentifier.country_code))),
            ),
            passport=ps.PassportPayload(
                document_type=passport.document_type, number=passport.number,
                issuing_country_code=passport.issuing_country_code,
                issue_date=passport.issue_date, expiry_date=passport.expiry_date,
                details=passport.details,
                has_other_valid_passport=bool(secondary_passports),
                other_passport_details=self._secondary_passport_details(secondary_passports) or None,
            ),
            secondary_passports=tuple(ps.SecondaryPassportPayload(
                number=item.number, issuing_country_code=item.issuing_country_code,
                issue_date=item.issue_date, expiry_date=item.expiry_date, details=item.details,
            ) for item in secondary_passports),
            contacts=contacts, residential_address=self._address(residential),
            mailing_address=self._address(mailing) if mailing else None,
            residences=residences,
            trip=ps.TripPayload(
                intake_purpose_text=trip.intake_purpose_text,
                imm5257_purpose_code=trip.imm5257_purpose_code,
                arrival_date=trip.arrival_date, departure_date=trip.departure_date,
                available_funds_amount=self._decimal(trip.available_funds_amount),
                available_funds_currency=trip.available_funds_currency,
                funds_source_reference=trip.funds_source_reference,
            ),
            hosts=hosts, funding=funding, family=family,
            education=tuple(ps.EducationPayload(
                level=item.level, institution_name=item.institution_name, course=item.course,
                details=item.details, start_date=item.start_date, end_date=item.end_date,
                city=item.city, state_province=item.state_province, country_code=item.country_code,
                is_primary=item.is_primary, sort_order=item.sort_order,
            ) for item in self.session.scalars(select(cm.EducationRecord).where(
                cm.EducationRecord.application_id == app.id,
                cm.EducationRecord.person_id == person.id,
            ).order_by(cm.EducationRecord.sort_order))),
            activities=tuple(ps.ActivityPayload(
                activity_type=item.activity_type, position=item.position,
                organization_name=item.organization_name, duties=item.duties,
                start_date=item.start_date, end_date=item.end_date,
                period_status=item.period_status, city=item.city,
                state_province=item.state_province, country_code=item.country_code,
                sort_order=item.sort_order,
            ) for item in self.session.scalars(select(cm.ActivityRecord).where(
                cm.ActivityRecord.application_id == app.id,
                cm.ActivityRecord.person_id == person.id,
            ).order_by(cm.ActivityRecord.sort_order))),
            residence_history=tuple(ps.ResidenceHistoryPayload(
                country_code=item.country_code, status_or_purpose=item.status_or_purpose,
                start_date=item.start_date, end_date=item.end_date, sort_order=item.sort_order,
            ) for item in self.session.scalars(select(cm.ResidenceHistoryRecord).where(
                cm.ResidenceHistoryRecord.application_id == app.id,
                cm.ResidenceHistoryRecord.person_id == person.id,
            ).order_by(cm.ResidenceHistoryRecord.sort_order))),
            travel_history=tuple(ps.TravelHistoryPayload(
                country_code=item.country_code, purpose=item.purpose,
                entry_date=item.entry_date, exit_date=item.exit_date, sort_order=item.sort_order,
            ) for item in self.session.scalars(select(cm.TravelHistoryRecord).where(
                cm.TravelHistoryRecord.application_id == app.id,
                cm.TravelHistoryRecord.person_id == person.id,
            ).order_by(cm.TravelHistoryRecord.sort_order))),
            official_answers=tuple(ps.OfficialAnswerPayload(question_code=item.question_code, answer=item.answer) for item in self.session.scalars(select(cm.OfficialApplicationAnswer).where(
                cm.OfficialApplicationAnswer.application_id == app.id
            ).order_by(cm.OfficialApplicationAnswer.question_code))),
            official_explanations=tuple(ps.OfficialExplanationPayload(section_code=item.section_code, text=item.text) for item in self.session.scalars(select(cm.OfficialExplanation).where(
                cm.OfficialExplanation.application_id == app.id
            ).order_by(cm.OfficialExplanation.section_code))),
            representative=ps.RepresentativePayload(
                action=authorization.action, revision_number=revision.revision_number,
                family_name=revision.family_name, given_names=revision.given_names,
                organization_name=revision.organization_name, unit=revision.unit,
                street_number=revision.street_number, street_name=revision.street_name,
                city=revision.city, province=revision.province, country_code=revision.country_code,
                postal_code=revision.postal_code, phone_country_code=revision.phone_country_code,
                phone_number=revision.phone_number, email=revision.email, category=revision.category,
                membership_number=revision.membership_number, membership_province=revision.membership_province,
                other_category_details=revision.other_category_details,
                supervising_lawyer=revision.supervising_lawyer,
                supervising_lawyer_membership=revision.supervising_lawyer_membership,
                cancelled_representative_name=self._display_name(cancelled) if cancelled else None,
                cancelled_representative_family_name=cancelled.last_name if cancelled else None,
                cancelled_representative_given_names=cancelled.first_name if cancelled else None,
                cancelled_organization_name=authorization.cancelled_organization_name,
            ),
        )

    def _address(self, item):
        return ps.AddressPayload(
            context=item.context, po_box=item.po_box, unit=item.unit,
            street_number=item.street_number, street_name=item.street_name,
            city=item.city, state_province=item.state_province,
            postal_code=item.postal_code, country_code=item.country_code,
            unstructured_source_text=item.unstructured_source_text,
        )

    def _host(self, item):
        party = self.session.get(models.Person, item.person_id) if item.person_id else self.session.get(cm.Organization, item.organization_id)
        address = self.session.get(cm.Address, item.address_id) if item.address_id else None
        return ps.HostPayload(
            host_type=item.host_type,
            display_name=self._display_name(party) if isinstance(party, models.Person) else party.legal_name,
            relationship_to_applicant=item.relationship_to_applicant,
            family_relationship=item.family_relationship,
            immigration_status_in_canada=item.immigration_status_in_canada,
            address=self._address(address) if address else None,
            email=item.email, phone=item.phone, is_primary=item.is_primary, sort_order=item.sort_order,
        )

    def _funding(self, item):
        party = self.session.get(models.Person, item.person_id) if item.person_id else self.session.get(cm.Organization, item.organization_id) if item.organization_id else None
        party_name = self._display_name(party) if isinstance(party, models.Person) else party.legal_name if party else None
        return ps.FundingPayload(
            payer_kind=item.payer_kind, party_name=party_name, description=item.description,
            amount=self._decimal(item.amount) if item.amount is not None else None,
            currency=item.currency, is_primary=item.is_primary, sort_order=item.sort_order,
        )

    def _family(self, item):
        person = self.session.get(models.Person, item.related_person_id)
        bio = self.session.get(cm.PersonBiography, person.id)
        address = self.session.get(cm.Address, item.address_id) if item.address_id else None
        return ps.FamilyRelationshipPayload(
            relationship_type=item.relationship_type, parent_type=item.parent_type,
            guardian_status=item.guardian_status, is_current=item.is_current,
            relationship_start_date=item.relationship_start_date,
            relationship_end_date=item.relationship_end_date,
            previous_relationship_type=item.previous_relationship_type,
            accompanying_applicant=item.accompanying_applicant,
            residence_same_as_applicant=item.residence_same_as_applicant,
            death_details=item.death_details, address=self._address(address) if address else None,
            related_person=ps.RelatedPersonPayload(
                family_name=person.last_name, given_names=person.first_name,
                date_of_birth=bio.date_of_birth if bio else None,
                birth_country_code=bio.birth_country_code if bio else None,
                marital_status=bio.marital_status if bio else None,
                occupation_text=bio.occupation_text if bio else None,
            ), sort_order=item.sort_order,
        )

    @staticmethod
    def _display_name(person):
        return " ".join(part for part in (person.first_name, person.last_name) if part).strip()

    @staticmethod
    def _decimal(value: Any) -> str:
        decimal = Decimal(str(value))
        rendered = format(decimal, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return rendered or "0"

    @staticmethod
    def _secondary_passport_details(items) -> str:
        rows = []
        for item in items:
            values = [item.number, item.issuing_country_code]
            values.extend(value.isoformat() for value in (item.issue_date, item.expiry_date) if value)
            if item.details: values.append(item.details)
            rows.append(" | ".join(values))
        return "\n".join(rows)
