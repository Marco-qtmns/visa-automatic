from __future__ import annotations

import hashlib
import logging
import tempfile
import uuid
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePath
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from canada.case_store import load_case
from canada.models import CanadaCase
from canada.representative_store import load_profile_into_case
from canada.source_readers import read_google_forms_csv

from .. import models
from ..config.canada_import_mapping import AUDITED_GENERATOR_MAPPINGS, MAPPING_VERSION, MappingEntry
from ..models import canada as cm
from .address_normalization import normalize_address
from .core import DomainNotFound, DomainValidationError
from .country_normalization import ISO_ALPHA3_CODES, normalize_country, split_country_values
from .person_roles import add_authoritative_role


SOURCE_LIMITS = {
    "google_verified_csv": 5 * 1024 * 1024,
    "canada_case_json": 20 * 1024 * 1024,
    "representative_profile_json": 1024 * 1024,
}

SECTIONS = {
    "identity": "Applicant", "passport": "Passport", "contact": "Contact",
    "trip": "Trip", "relationships": "Family", "family": "Family",
    "education": "Education", "activities": "Activities",
    "residence_records": "History", "travel_records": "History",
    "official_review": "Official answers", "representative": "Representative",
    "staff_review": "Application",
}

LABELS = {
    "family_name": "Family name", "given_names": "Given names",
    "date_of_birth": "Date of birth", "number": "Passport number",
    "issuing_country": "Passport issuing country", "issue_date": "Issue date",
    "expiry_date": "Expiry date", "purpose": "Purpose of travel",
    "arrival_date": "Arrival date", "departure_date": "Departure date",
    "email": "Email", "phone": "Phone", "address": "Address",
    "application_date": "Official application date",
}

# These are the audited import targets whose canonical storage contract is an
# ISO-3166 alpha-3 code. Phone prefixes and free-text addresses are excluded.
COUNTRY_CODE_TARGETS = frozenset({
    ("person_biography", "birth_country_code"),
    ("family_biography", "birth_country_code"),
    ("citizenship", "country_code"),
    ("residence", "country_code"),
    ("person_identifier", "country_code"),
    ("travel_document", "issuing_country_code"),
    ("address", "country_code"),
    ("education", "country_code"),
    ("activity", "country_code"),
    ("residence_history", "country_code"),
    ("travel_history", "country_code"),
    ("representative_profile", "country"),
})
LOGGER = logging.getLogger(__name__)


class LegacySourceAdapter:
    source_type: str

    def parse(self, content: bytes, filename: str) -> CanadaCase:
        raise NotImplementedError

class CanadaCaseImportAdapter(LegacySourceAdapter):
    source_type = "canada_case_json"

    def parse(self, content: bytes, filename: str) -> CanadaCase:
        if not PurePath(filename).name.endswith(".canada-case.json"):
            raise DomainValidationError("expected a .canada-case.json source")
        with _temporary_file(content, ".canada-case.json") as path:
            return load_case(path)


class VerifiedGoogleImportAdapter(LegacySourceAdapter):
    source_type = "google_verified_csv"

    def parse(self, content: bytes, filename: str) -> CanadaCase:
        if not PurePath(filename).name.casefold().endswith(".csv"):
            raise DomainValidationError("expected a verified Google Forms CSV source")
        with _temporary_file(content, ".csv") as path:
            cases = read_google_forms_csv(path)
        if len(cases) != 1:
            raise DomainValidationError("preview requires a CSV containing exactly one response")
        return cases[0]


class RepresentativeProfileImportAdapter(LegacySourceAdapter):
    source_type = "representative_profile_json"

    def parse(self, content: bytes, filename: str) -> CanadaCase:
        if not PurePath(filename).name.endswith(".canada-representative.json"):
            raise DomainValidationError("expected a .canada-representative.json source")
        case = CanadaCase()
        with _temporary_file(content, ".canada-representative.json") as path:
            load_profile_into_case(case, path)
        return case


class _temporary_file:
    def __init__(self, content: bytes, suffix: str):
        self.content, self.suffix, self.path = content, suffix, None

    def __enter__(self) -> Path:
        handle = tempfile.NamedTemporaryFile(suffix=self.suffix, delete=False)
        handle.write(self.content)
        handle.close()
        self.path = Path(handle.name)
        return self.path

    def __exit__(self, *_args):
        if self.path:
            self.path.unlink(missing_ok=True)


ADAPTERS = {
    adapter.source_type: adapter
    for adapter in (CanadaCaseImportAdapter(), VerifiedGoogleImportAdapter(), RepresentativeProfileImportAdapter())
}


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime, Decimal, uuid.UUID)):
        return str(value)
    return value


def _date(value: Any) -> date | None:
    if _blank(value):
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise DomainValidationError(f"unsupported legacy date: {text}")


def _country(value: Any) -> str | None:
    return normalize_country(value).code


def _yes_no(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text in {"yes", "sim", "oui", "ja"}: return "yes"
    if text in {"no", "não", "nao", "non", "nein"}: return "no"
    if text in {"n/a", "not applicable", "not_applicable"}: return "not_applicable"
    return "unknown"


def _bool(value: Any) -> bool | None:
    answer = _yes_no(value)
    return True if answer == "yes" else False if answer == "no" else None


def _equal(left: Any, right: Any) -> bool:
    if isinstance(left, Decimal): left = float(left)
    if isinstance(right, Decimal): right = float(right)
    return _json_value(left) == _json_value(right)


class CanadaLegacyImportService:
    """Anti-corruption boundary from the tested legacy CanadaCase to M9A entities."""

    def __init__(self, session: Session):
        self.session = session

    def preview_upload(self, case_id: uuid.UUID, source_type: str, content: bytes,
                       filename: str, imported_by: str | None = None) -> cm.CanadaLegacyImportRun:
        if source_type not in ADAPTERS:
            raise DomainValidationError("unsupported Canada import source type")
        if not content:
            raise DomainValidationError("import source is empty")
        if len(content) > SOURCE_LIMITS[source_type]:
            raise DomainValidationError("Canada import source exceeds the configured size limit")
        source_hash = hashlib.sha256(content).hexdigest()
        existing = self.session.scalar(select(cm.CanadaLegacyImportRun).where(
            cm.CanadaLegacyImportRun.case_id == case_id,
            cm.CanadaLegacyImportRun.source_type == source_type,
            cm.CanadaLegacyImportRun.source_hash == source_hash,
            cm.CanadaLegacyImportRun.mapping_version == MAPPING_VERSION,
        ))
        if existing:
            return existing
        try:
            legacy_case = ADAPTERS[source_type].parse(content, PurePath(filename).name)
        except (OSError, UnicodeError, ValueError, DomainValidationError) as error:
            failed = cm.CanadaLegacyImportRun(
                case_id=case_id, source_type=source_type,
                source_identifier=PurePath(filename).name[:255], source_hash=source_hash,
                mapping_version=MAPPING_VERSION, status="failed", imported_by=imported_by,
                error_summary=str(error)[:1000], completed_at=datetime.now(timezone.utc),
            )
            self.session.add(failed)
            try:
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
            raise DomainValidationError(f"invalid Canada import source: {error}") from error
        return self.preview_case(
            case_id, legacy_case, source_type=source_type,
            source_identifier=PurePath(filename).name, source_hash=source_hash,
            imported_by=imported_by,
        )

    def preview_case(self, case_id: uuid.UUID, legacy: CanadaCase, *, source_type: str,
                     source_identifier: str, source_hash: str | None = None,
                     imported_by: str | None = None) -> cm.CanadaLegacyImportRun:
        case = self.session.get(models.Case, case_id)
        if case is None: raise DomainNotFound("Case not found")
        app = self.session.scalar(select(cm.CanadaApplication).where(cm.CanadaApplication.case_id == case_id))
        if app is None:
            app = cm.CanadaApplication(case_id=case_id)
            self.session.add(app)
            self.session.flush()
        digest = source_hash or hashlib.sha256(repr(asdict(legacy)).encode()).hexdigest()
        existing = self.session.scalar(select(cm.CanadaLegacyImportRun).where(
            cm.CanadaLegacyImportRun.case_id == case_id,
            cm.CanadaLegacyImportRun.source_type == source_type,
            cm.CanadaLegacyImportRun.source_hash == digest,
            cm.CanadaLegacyImportRun.mapping_version == MAPPING_VERSION,
        ))
        if existing: return existing
        run = cm.CanadaLegacyImportRun(
            case_id=case_id, source_type=source_type,
            source_identifier=PurePath(source_identifier).name[:255], source_hash=digest,
            mapping_version=MAPPING_VERSION, imported_by=imported_by,
        )
        self.session.add(run)
        self.session.flush()
        warnings: list[str] = []
        self._host_type_proposal = self._propose_host_type(legacy)
        for mapping, record_key, value, source_classification in self._legacy_values(legacy):
            if _blank(value):
                continue
            candidate = self._candidate(run, app, mapping, record_key, value, warnings, source_classification)
            if candidate is not None:
                self.session.add(candidate)
        self.session.flush()
        run.warnings_json = warnings
        self._refresh_counts(run)
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise DomainValidationError("could not persist Canada import preview") from error
        self.session.refresh(run)
        return run

    def _legacy_values(self, legacy: CanadaCase) -> Iterable[tuple[MappingEntry, str, Any, str]]:
        for mapping in AUDITED_GENERATOR_MAPPINGS:
            group, field = mapping.legacy_path.rsplit(".", 1)
            source_classification = mapping.source_classification
            origin = legacy.overrides.get(mapping.legacy_path) or legacy.provenance.get(mapping.legacy_path)
            if origin and "narrative" in origin.source_type.casefold():
                source_classification = "legacy_narrative_derived"
            elif origin and "deriv" in origin.source_type.casefold():
                source_classification = "legacy_derived"
            if group == "activities[*]":
                for index, item in enumerate(legacy.activities):
                    key = f"activity:{item.source_role or 'legacy'}:{item.source_block_index or index + 1}"
                    yield mapping, key, getattr(item, field, ""), source_classification
            elif group == "family.members[*]":
                for kind, items in (("parent", legacy.family.parents), ("child", legacy.family.children)):
                    for index, item in enumerate(items):
                        key = f"{kind}:{item.source_role or 'legacy'}:{item.source_block_index or index + 1}"
                        yield mapping, key, getattr(item, field, ""), source_classification
            elif group in {"residence_records[*]", "travel_records[*]"}:
                items = legacy.residence_records if group.startswith("residence") else legacy.travel_records
                prefix = "residence" if group.startswith("residence") else "travel"
                for index, item in enumerate(items):
                    key = f"{prefix}:{item.source_role or 'legacy'}:{item.source_block_index or index + 1}"
                    yield mapping, key, getattr(item, field, ""), source_classification
            elif group == "identity" and field == "other_citizenship":
                for index, citizenship in enumerate(
                    split_country_values(getattr(legacy.identity, field, "")), start=1
                ):
                    yield (
                        mapping, f"citizenship:other:{index}", citizenship,
                        source_classification,
                    )
            else:
                yield mapping, "scalar", getattr(getattr(legacy, group), field, ""), source_classification

    def _candidate(self, run: cm.CanadaLegacyImportRun, app: cm.CanadaApplication,
                   mapping: MappingEntry, record_key: str, raw: Any,
                   warnings: list[str], source_classification: str) -> cm.CanadaImportCandidate | None:
        group, field = mapping.legacy_path.rsplit(".", 1)
        entity_type, entity, target_field = self._target(app, group, field, record_key)
        warning_count = len(warnings)
        proposed = self._transform(
            group, field, raw, warnings, record_key,
            target_entity_type=entity_type, target_field=target_field,
        )
        if (
            group == "trip" and field == "visiting_person_or_institution"
            and getattr(self, "_host_type_proposal", None)
        ):
            proposed = self._host_type_proposal
        transform_invalid = len(warnings) > warning_count
        if proposed is None and field not in {"post_secondary_education"}:
            return None
        current = getattr(entity, target_field, None) if entity is not None and target_field != "*" else None
        entity_id = (
            getattr(entity, "id", getattr(entity, "person_id", None))
            if entity is not None else None
        )
        status = "same" if entity is not None and _equal(current, proposed) else "new"
        conflict_type = None
        if field in {"address", "mailing_address", "spouse_address", "host_address"}:
            parsed = normalize_address(raw)
            detail = ", ".join(parsed.parse_issues) or "employee confirmation required"
            if parsed.unresolved_text:
                detail = f"{detail}; unresolved: {parsed.unresolved_text}"
            warnings.append(
                f"{mapping.legacy_path}: original address preserved; parsed components need review ({detail})"
            )
        if group == "family.members[*]" and record_key.startswith("parent:") and field == "relationship":
            warnings.append(f"{record_key}: parent role is not specific enough to infer mother/father")
        if group == "representative" and field == "cancelled_family_name":
            status, conflict_type = "ambiguous", "representative_person_selection_required"
            warnings.append("A cancelled representative must be selected by canonical person ID; name-only matching is forbidden.")
        elif group == "representative" and field in {"action", "cancelled_organization"} and entity is None:
            status, conflict_type = "ambiguous", "representative_authorization_selection_required"
            warnings.append("Representative authorization remains an explicit case selection and was not created by profile import.")
        if group == "trip" and field in {"visiting_person_or_institution", "host_name"}:
            status, conflict_type = "ambiguous", "host_type_ambiguous"
            warnings.append("Host type must be selected explicitly; person/institution was not guessed.")
        elif transform_invalid:
            status, conflict_type = "ambiguous", "invalid_value"
        elif entity is not None and not _blank(current) and not _equal(current, proposed):
            status, conflict_type = "conflict", "different_canonical_value"
        if entity_id is not None and self._reviewed(
            run.case_id, entity_type, entity_id, target_field
        ) and not _equal(current, proposed):
            status, conflict_type = "conflict", "confirmed_canonical_value"
        contradiction = self._fact_contradiction(run.case_id, group, field, proposed)
        if contradiction:
            status, conflict_type = "conflict", contradiction
            warnings.append("Imported structured data contradicts a confirmed case fact.")
        return cm.CanadaImportCandidate(
            import_run_id=run.id, domain_section=SECTIONS.get(group.split("[")[0], "Application"),
            employee_label=LABELS.get(field, field.replace("_", " ").title()),
            target_entity_type=entity_type, target_entity_id=entity_id,
            target_field=target_field, operation="create_or_set" if entity is None else "set_field",
            source_path=mapping.legacy_path, source_record_key=record_key,
            source_classification=source_classification,
            source_reference=f"{run.source_type}:{run.source_identifier}#{mapping.legacy_path}",
            raw_value_json=_json_value(raw),
            proposed_value_json=_json_value(proposed), current_value_json=_json_value(current),
            status=status, conflict_type=conflict_type,
            review_policy=mapping.review_policy, conflict_policy=mapping.conflict_policy,
        )

    def _target(self, app: cm.CanadaApplication, group: str, field: str, key: str):
        applicant = self.session.get(models.Person, app.applicant_person_id) if app.applicant_person_id else None
        if group == "identity":
            if field in {"family_name", "given_names"}:
                return "person", applicant, "last_name" if field == "family_name" else "first_name"
            if field in {"residence_country", "residence_status", "residence_since"}:
                entity = self.session.scalar(select(cm.ApplicantResidence).where(cm.ApplicantResidence.application_id == app.id, cm.ApplicantResidence.is_current.is_(True)))
                return "residence", entity, {"residence_country":"country_code", "residence_status":"immigration_status_code", "residence_since":"resident_since"}[field]
            if field in {"nationality", "other_citizenship"}:
                entity = self.session.scalar(select(cm.PersonCitizenship).where(cm.PersonCitizenship.person_id == applicant.id, cm.PersonCitizenship.is_primary.is_(field == "nationality"))) if applicant else None
                return "citizenship", entity, "country_code"
            entity = self.session.get(cm.PersonBiography, applicant.id) if applicant else None
            return "person_biography", entity, {"birth_country":"birth_country_code", "city_of_birth":"birth_city", "state_of_birth":"birth_state_province"}.get(field, field)
        if group == "passport":
            if field.startswith("identity_"):
                entity = self.session.scalar(select(cm.PersonIdentifier).where(cm.PersonIdentifier.person_id == applicant.id, cm.PersonIdentifier.identifier_type == "national_identity")) if applicant else None
                return "person_identifier", entity, {"identity_number":"value", "identity_country":"country_code", "identity_issue_date":"issue_date", "identity_expiry_date":"expiry_date"}[field]
            entity = self.session.scalar(select(cm.TravelDocument).where(cm.TravelDocument.application_id == app.id, cm.TravelDocument.is_primary.is_(True)))
            return "travel_document", entity, {"issuing_country":"issuing_country_code", "other_passport_details":"details"}.get(field, field)
        if group == "contact":
            if field in {"email", "phone"}:
                entity = self.session.scalar(select(cm.ContactPoint).where(cm.ContactPoint.person_id == applicant.id, cm.ContactPoint.type == field, cm.ContactPoint.is_primary.is_(True))) if applicant else None
                return "contact", entity, "value"
            context = "mailing" if field.startswith("mailing_") or field == "mailing_address" else "residential"
            entity = self.session.scalar(select(cm.Address).where(cm.Address.application_id == app.id, cm.Address.context == context, cm.Address.owner_id == app.id))
            target = {"address":"unstructured_source_text", "mailing_address":"unstructured_source_text", "state":"state_province", "postcode":"postal_code", "country":"country_code"}.get(field, field.removeprefix("residential_").removeprefix("mailing_"))
            return "address", entity, target
        if group == "trip":
            trip = self.session.scalar(select(cm.TripPlan).where(cm.TripPlan.application_id == app.id))
            if field in {"payer", "payer_details"}:
                entity = self.session.scalar(select(cm.FundingSource).where(cm.FundingSource.trip_plan_id == trip.id, cm.FundingSource.is_primary.is_(True))) if trip else None
                return "funding_source", entity, "payer_kind" if field == "payer" else "description"
            if field.startswith("host_") or field in {"visiting_person_or_institution", "relationship", "family_relationship"}:
                entity = self.session.scalar(select(cm.HostRecord).where(cm.HostRecord.trip_plan_id == trip.id, cm.HostRecord.is_primary.is_(True))) if trip else None
                target = {"host_name":"party_name", "visiting_person_or_institution":"host_type", "relationship":"relationship_to_applicant", "host_status":"immigration_status_in_canada", "host_phone":"phone", "host_email":"email", "host_address":"address"}.get(field, field)
                return "host", entity, target
            target = {"purpose":"intake_purpose_text", "available_funds_cad":"available_funds_amount", "estimated_spend_currency":"available_funds_currency"}.get(field, field)
            return "trip_plan", trip, target
        if group == "education":
            entity = self._linked_or_first(app, "education", key, cm.EducationRecord)
            return "education", entity, {"institution":"institution_name", "country":"country_code", "state":"state_province", "post_secondary_details":"details"}.get(field, field)
        if group == "activities[*]":
            entity = self._linked_or_first(app, "activity", key, cm.ActivityRecord, fallback=False)
            return "activity", entity, {"organization":"organization_name", "country":"country_code", "state":"state_province", "status":"period_status", "ongoing_answer":"period_status"}.get(field, field)
        if group == "family.members[*]":
            entity = self._linked_entity(app.case_id, "family_relationship", key, cm.FamilyRelationship)
            if field in {"relationship"}:
                return "family_relationship", entity, "relationship_type"
            if field == "address":
                address = self.session.get(cm.Address, entity.address_id) if entity and entity.address_id else None
                return "address", address, "unstructured_source_text"
            person = self.session.get(models.Person, entity.related_person_id) if entity else None
            if field in {"family_name", "given_names"}:
                return "family_person", person, "last_name" if field == "family_name" else "first_name"
            bio = self.session.get(cm.PersonBiography, person.id) if person else None
            return "family_biography", bio, {"birth_country":"birth_country_code"}.get(field, field)
        if group == "relationships":
            kind = "former_spouse" if field.startswith("former_") or field.startswith("previous_") else "spouse"
            entity = self._linked_entity(app.case_id, "family_relationship", kind, cm.FamilyRelationship)
            if field in {"marriage_start_date", "previous_start_date", "previous_end_date", "previous_relationship_type", "spouse_accompanying_answer"}:
                target = {"marriage_start_date":"relationship_start_date", "previous_start_date":"relationship_start_date", "previous_end_date":"relationship_end_date", "spouse_accompanying_answer":"accompanying_applicant"}.get(field, field)
                return "family_relationship", entity, target
            if field == "spouse_address":
                address = self.session.get(cm.Address, entity.address_id) if entity and entity.address_id else None
                return "address", address, "unstructured_source_text"
            person = self.session.get(models.Person, entity.related_person_id) if entity else None
            if field.endswith("family_name") or field.endswith("given_names"):
                return "family_person", person, "last_name" if field.endswith("family_name") else "first_name"
            bio = self.session.get(cm.PersonBiography, person.id) if person else None
            target = "date_of_birth" if field.endswith("date_of_birth") else "occupation_text" if field.endswith("occupation") else "birth_country_code" if field.endswith("birth_country") else field
            return "family_biography", bio, target
        if group in {"residence_records[*]", "travel_records[*]"}:
            etype = "residence_history" if group.startswith("residence") else "travel_history"
            model = cm.ResidenceHistoryRecord if etype == "residence_history" else cm.TravelHistoryRecord
            entity = self._linked_entity(app.case_id, etype, key, model)
            target = {"country":"country_code", "start_date":"start_date" if etype == "residence_history" else "entry_date", "end_date":"end_date" if etype == "residence_history" else "exit_date", "status_or_purpose":"status_or_purpose" if etype == "residence_history" else "purpose"}[field]
            return etype, entity, target
        if group == "official_review":
            entity = self.session.scalar(select(cm.OfficialApplicationAnswer).where(cm.OfficialApplicationAnswer.application_id == app.id, cm.OfficialApplicationAnswer.question_code == field))
            return "official_answer", entity, "answer"
        if group == "representative":
            if field in {"action", "cancelled_family_name", "cancelled_organization"}:
                entity = self.session.scalar(select(cm.RepresentativeAuthorization).where(cm.RepresentativeAuthorization.application_id == app.id))
                target = {"action":"action", "cancelled_family_name":"cancelled_representative_person_id", "cancelled_organization":"cancelled_organization_name"}[field]
                return "representative_authorization", entity, target
            return "representative_profile", None, field
        return "application", app, "official_application_date"

    def _linked_entity(self, case_id, entity_type, key, model):
        link = self.session.scalar(select(cm.LegacyImportEntityLink).where(
            cm.LegacyImportEntityLink.case_id == case_id,
            cm.LegacyImportEntityLink.source_record_key == key,
            cm.LegacyImportEntityLink.canonical_entity_type == entity_type,
        ))
        return self.session.get(model, link.canonical_entity_id) if link else None

    def _linked_family_relationship(self, run, key):
        """Reuse a generic parent link only after the current parser supplied an explicit role."""
        linked = self._linked_entity(
            run.case_id, "family_relationship", key, cm.FamilyRelationship
        )
        if linked is not None:
            return linked
        parts = key.split(":", 2)
        if (
            run.source_type != "google_verified_csv"
            or len(parts) != 3
            or parts[0] != "parent"
            or parts[1] not in {"father", "mother"}
        ):
            return None
        legacy_key = f"parent:parent:{parts[2]}"
        relationship = self._linked_entity(
            run.case_id, "family_relationship", legacy_key, cm.FamilyRelationship
        )
        if relationship is None or relationship.relationship_type != "parent":
            return None
        if relationship.parent_type not in {None, parts[1]}:
            return None

        old_links = list(self.session.scalars(select(cm.LegacyImportEntityLink).where(
            cm.LegacyImportEntityLink.case_id == run.case_id,
            cm.LegacyImportEntityLink.source_type == run.source_type,
            cm.LegacyImportEntityLink.source_record_key == legacy_key,
        )))
        for old_link in old_links:
            collision = self.session.scalar(select(cm.LegacyImportEntityLink.id).where(
                cm.LegacyImportEntityLink.case_id == run.case_id,
                cm.LegacyImportEntityLink.source_type == run.source_type,
                cm.LegacyImportEntityLink.source_record_key == key,
                cm.LegacyImportEntityLink.canonical_entity_type == old_link.canonical_entity_type,
            ))
            if collision is not None:
                return None

        relationship.parent_type = parts[1]
        for old_link in old_links:
            old_link.source_record_key = key
            old_link.last_import_run_id = run.id
        self.session.flush()
        return relationship

    def _linked_or_first(self, app, entity_type, key, model, fallback=True):
        linked = self._linked_entity(app.case_id, entity_type, key, model)
        if linked or not fallback: return linked
        return self.session.scalar(select(model).where(model.application_id == app.id).order_by(model.sort_order))

    def _transform(
        self, group, field, value, warnings, record_key="scalar", *,
        target_entity_type=None, target_field=None,
    ):
        value = value.strip() if isinstance(value, str) else value
        if field.endswith("date") or field.endswith("date_of_birth") or field in {"start_date", "end_date", "date_of_birth", "residence_since", "arrival_date", "departure_date", "application_date"}:
            try: return _date(value)
            except DomainValidationError:
                warnings.append(f"{group}.{field}: date needs manual review")
                return value
        if (target_entity_type, target_field) in COUNTRY_CODE_TARGETS:
            code = _country(value)
            if code is None:
                warnings.append(f"{group}.{field}: country needs ISO-code review")
                return value
            return code
        if group == "official_review": return _yes_no(value)
        if group == "family.members[*]" and field == "relationship":
            return record_key.split(":", 1)[0]
        if field in {"mailing_same_as_residential", "spouse_accompanying_answer"}: return _bool(value)
        if field == "available_funds_cad":
            try: return float(Decimal(str(value).replace(" ", "").replace(",", ".")))
            except (InvalidOperation, ValueError):
                warnings.append("Available funds needs numeric review")
                return value
        if field in {"status", "ongoing_answer"}:
            text = str(value).casefold()
            return "current" if text in {"current", "ongoing", "yes", "sim"} else "completed" if text in {"completed", "no", "não", "nao"} else "unknown"
        return value

    def _reviewed(self, case_id, entity_type, entity_id, field):
        if entity_type not in {item.value for item in cm.ProvenanceEntityType}: return False
        return bool(self.session.scalar(select(cm.FieldProvenanceReview.id).where(
            cm.FieldProvenanceReview.case_id == case_id,
            cm.FieldProvenanceReview.entity_type == entity_type,
            cm.FieldProvenanceReview.entity_id == entity_id,
            cm.FieldProvenanceReview.field_key == field,
            cm.FieldProvenanceReview.review_state.in_(["confirmed", "corrected"]),
            cm.FieldProvenanceReview.superseded_at.is_(None),
        )))

    def _fact_contradiction(self, case_id, group, field, proposed):
        keys = []
        if group == "trip" and field in {"payer", "payer_details"}: keys.append("sponsor.exists")
        if group == "trip" and (field.startswith("host_") or field == "visiting_person_or_institution"): keys.append("host.exists")
        if not keys: return None
        fact = self.session.scalar(select(models.Fact).where(models.Fact.case_id == case_id, models.Fact.key.in_(keys), models.Fact.status == "confirmed").order_by(models.Fact.created_at.desc()))
        return "confirmed_fact_contradiction" if fact and fact.value_json is False and not _blank(proposed) else None

    @staticmethod
    def _propose_host_type(legacy: CanadaCase) -> str | None:
        """Use explicit relationship/type answers, never the host's name."""
        relationship = " ".join(filter(None, (
            legacy.trip.relationship, legacy.trip.family_relationship,
        ))).strip()
        if relationship:
            return "person"
        answer = str(legacy.trip.visiting_person_or_institution or "").casefold()
        if any(word in answer for word in ("instituição", "instituicao", "institution", "empresa", "company")):
            return "organization"
        if any(word in answer for word in ("pessoa", "person")):
            return "person"
        return None

    def list_runs(self, case_id):
        return list(self.session.scalars(select(cm.CanadaLegacyImportRun).where(cm.CanadaLegacyImportRun.case_id == case_id).order_by(cm.CanadaLegacyImportRun.created_at.desc())))

    def get_run(self, import_id):
        run = self.session.get(cm.CanadaLegacyImportRun, import_id)
        if run is None: raise DomainNotFound("Canada import run not found")
        return run

    def changes(self, import_id):
        self.get_run(import_id)
        items = list(self.session.scalars(select(cm.CanadaImportCandidate).where(cm.CanadaImportCandidate.import_run_id == import_id).order_by(cm.CanadaImportCandidate.domain_section, cm.CanadaImportCandidate.created_at)))
        for item in items:
            entity_type = {"family_person":"person", "family_biography":"person_biography"}.get(item.target_entity_type, item.target_entity_type)
            state = None
            if item.target_entity_id and entity_type in {value.value for value in cm.ProvenanceEntityType}:
                state = self.session.scalar(select(cm.FieldProvenanceReview.review_state).where(
                    cm.FieldProvenanceReview.entity_type == entity_type,
                    cm.FieldProvenanceReview.entity_id == item.target_entity_id,
                    cm.FieldProvenanceReview.field_key == item.target_field,
                    cm.FieldProvenanceReview.superseded_at.is_(None),
                ))
            setattr(item, "canonical_review_state", state)
        return items

    def review(self, candidate_id, decision, reviewed_by=None, *, host_type=None):
        item = self.session.get(cm.CanadaImportCandidate, candidate_id)
        if item is None: raise DomainNotFound("Canada import change not found")
        if item.status == "applied": raise DomainValidationError("applied import changes cannot be reviewed again")
        if decision == "accept":
            if item.status in {"conflict", "ambiguous"}: raise DomainValidationError("resolve conflicts and ambiguities explicitly")
            item.status = "accepted"
        elif decision in {"reject", "keep_current"}: item.status = "rejected"
        elif decision == "use_imported":
            if item.conflict_type in {"representative_authorization_selection_required", "representative_person_selection_required"}:
                raise DomainValidationError("complete representative selection in the canonical application before importing this field")
            if item.conflict_type == "host_type_ambiguous":
                if host_type not in {"person", "organization"}:
                    raise DomainValidationError("host type must be selected explicitly")
                item.conflict_type = f"resolved_host_{host_type}"
                if item.target_field == "host_type":
                    item.proposed_value_json = host_type
            item.status = "accepted"
        else: raise DomainValidationError("unsupported import review decision")
        item.reviewed_by, item.reviewed_at = reviewed_by, datetime.now(timezone.utc)
        run = self.get_run(item.import_run_id); run.status = "reviewing"
        self._refresh_counts(run); self.session.commit(); self.session.refresh(item)
        return item

    def confirm(self, candidate_id, value, reviewed_by=None, *, host_type=None):
        """Validate an employee correction and accept the existing proposal."""
        item = self.session.get(cm.CanadaImportCandidate, candidate_id)
        if item is None:
            raise DomainNotFound("Canada import change not found")
        proposed = value
        if (item.target_entity_type, item.target_field) in COUNTRY_CODE_TARGETS:
            result = normalize_country(value)
            if not result.code:
                raise self._candidate_apply_error(
                    item,
                    DomainValidationError(
                        "Country is unknown or ambiguous; enter an ISO alpha-3 code or a recognized country name."
                    ),
                )
            proposed = result.code
        else:
            proposed = _json_value(self._coerce_for_field(
                item.target_entity_type, item.target_field, value
            ))
        if item.conflict_type == "host_type_ambiguous":
            if host_type not in {"person", "organization"}:
                raise DomainValidationError("host type must be selected explicitly")
            item.conflict_type = f"resolved_host_{host_type}"
            if item.target_field == "host_type":
                proposed = host_type
        if item.status in {"applied", "same"}:
            run = self.get_run(item.import_run_id)
            model = self._model(item.target_entity_type)
            entity = self.session.get(model, item.target_entity_id) if model and item.target_entity_id else None
            if entity is None:
                raise DomainValidationError("Canonical field is unavailable for confirmation")
            changed = not _equal(item.proposed_value_json, proposed)
            if changed:
                item.proposed_value_json = proposed
                app = self.session.scalar(select(cm.CanadaApplication).where(
                    cm.CanadaApplication.case_id == run.case_id
                ))
                try:
                    self._apply_candidate(run, app, item)
                except Exception as error:
                    self.session.rollback()
                    raise self._candidate_apply_error(item, error) from error
                active = self.session.scalar(select(cm.FieldProvenanceReview).where(
                    cm.FieldProvenanceReview.case_id == run.case_id,
                    cm.FieldProvenanceReview.entity_id == item.target_entity_id,
                    cm.FieldProvenanceReview.field_key == item.target_field,
                    cm.FieldProvenanceReview.superseded_at.is_(None),
                ).order_by(cm.FieldProvenanceReview.created_at.desc()))
                if active:
                    active.review_state = "corrected"
                    active.reviewed_by = reviewed_by
                    active.reviewed_at = datetime.now(timezone.utc)
            else:
                self._provenance(
                    run, item, entity, review_state="confirmed", reviewed_by=reviewed_by
                )
            item.reviewed_by = reviewed_by
            item.reviewed_at = datetime.now(timezone.utc)
            self.session.commit()
            self.session.refresh(item)
            return item
        item.proposed_value_json = proposed
        item.status = "accepted"
        item.reviewed_by = reviewed_by
        item.reviewed_at = datetime.now(timezone.utc)
        run = self.get_run(item.import_run_id)
        run.status = "reviewing"
        self._refresh_counts(run)
        self.session.commit()
        self.session.refresh(item)
        return item

    def apply(self, import_id, *, mode="accepted", reviewed_by=None):
        run = self.get_run(import_id)
        if run.status == "applied": return run
        changes = self.changes(import_id)
        if mode == "safe":
            for item in changes:
                if self._is_safe_new(item, changes):
                    item.status, item.reviewed_by, item.reviewed_at = "accepted", reviewed_by, datetime.now(timezone.utc)
        accepted = [item for item in changes if item.status == "accepted"]
        try:
            app = self.session.scalar(select(cm.CanadaApplication).where(cm.CanadaApplication.case_id == run.case_id))
            if app is None:
                raise DomainValidationError("Canada application is missing")
            if app.applicant_person_id is None:
                self._create_imported_applicant(run, app, accepted)
            accepted = self._ensure_family_targets(run, app, accepted)
            accepted.sort(key=lambda item: (
                0 if item.source_path == "trip.host_name" else 1,
                item.created_at,
            ))
            representative = [item for item in accepted if item.target_entity_type == "representative_profile"]
            if representative:
                revision = self._apply_representative_batch(run, representative)
                for item in representative:
                    item.target_entity_id, item.status = revision.id, "applied"
                accepted = [item for item in accepted if item.target_entity_type != "representative_profile"]
            for item in accepted:
                try:
                    self._apply_candidate(run, app, item)
                except Exception as error:
                    raise self._candidate_apply_error(item, error) from error
                item.status = "applied"
            self.session.flush()
            unresolved = any(item.status in {"new", "conflict", "ambiguous", "accepted"} for item in changes)
            run.status = "reviewing" if unresolved else "applied"
            run.completed_at = None if unresolved else datetime.now(timezone.utc)
            self._refresh_counts(run)
            self.session.commit()
        except Exception as error:
            self.session.rollback()
            if isinstance(error, (DomainValidationError, DomainNotFound)): raise
            LOGGER.exception("Canada import batch failed", extra={"import_run_id": str(import_id)})
            failure = DomainValidationError(
                "Import could not be applied. Review the highlighted values and try again."
            )
            failure.api_detail = {
                "category": "persistence_failure",
                "code": "IMPORT_APPLY_FAILED",
                "section": "Application",
                "field_path": None,
                "entity_id": None,
                "message": "Import could not be applied.",
                "rejected_value": None,
                "suggested_correction": "Retry the import. If it fails again, contact an administrator with the import run ID.",
                "retryable": True,
                "issues": [{"message": "The transaction was rolled back; no imported values were partially applied."}],
            }
            raise failure from error
        self.session.refresh(run)
        return run

    @staticmethod
    def _is_safe_new(item: cm.CanadaImportCandidate,
                     changes: list[cm.CanadaImportCandidate]) -> bool:
        """The single integrity gate for unattended canonical writes."""
        if not (
            item.status == "new"
            and _blank(item.current_value_json)
            and item.conflict_type is None
            and item.source_classification == "applicant_direct"
            and item.review_policy == "safe_direct_batch"
            and item.target_field != "*"
            and item.source_path in {entry.legacy_path for entry in AUDITED_GENERATOR_MAPPINGS}
        ):
            return False
        def identity(candidate):
            record_key = candidate.source_record_key
            if candidate.target_entity_type.startswith("family_") and record_key == "scalar":
                record_key = "former_spouse" if (
                    "former_" in candidate.source_path or "previous_" in candidate.source_path
                ) else "spouse"
            return (
                candidate.target_entity_type,
                str(candidate.target_entity_id) if candidate.target_entity_id else record_key,
                candidate.target_field,
            )
        item_identity = identity(item)
        relevant = [candidate for candidate in changes if candidate.id != item.id and (
            identity(candidate) == item_identity
        )]
        return not any(
            candidate.status in {"new", "conflict", "ambiguous", "accepted"}
            or not _equal(candidate.proposed_value_json, item.proposed_value_json)
            for candidate in relevant
        )

    def _apply_candidate(self, run, app, item):
        value = self._coerce_for_field(
            item.target_entity_type, item.target_field, item.proposed_value_json
        )
        entity = self.session.get(self._model(item.target_entity_type), item.target_entity_id) if item.target_entity_id and self._model(item.target_entity_type) else None
        if entity is None:
            entity = self._create_target(run, app, item, value)
            item.target_entity_id = getattr(entity, "id", getattr(entity, "person_id", None))
        if item.target_entity_type == "host" and item.target_field == "address":
            self._apply_host_address(app, entity, value)
            self.session.add(entity); self.session.flush()
            self._provenance(run, item, entity)
            return
        if item.target_entity_type == "host" and item.target_field == "party_name":
            if entity.host_type == "person":
                parts = str(value or "").split()
                if len(parts) < 2:
                    raise DomainValidationError("A person host requires both given and family names")
                party = self.session.get(models.Person, entity.person_id)
                party.first_name, party.last_name = " ".join(parts[:-1]), parts[-1]
            else:
                party = self.session.get(cm.Organization, entity.organization_id)
                party.legal_name = str(value or "").strip()
            self.session.add(party); self.session.flush()
            self._provenance(run, item, entity)
            return
        if item.target_entity_type == "address" and item.target_field == "unstructured_source_text":
            self._apply_normalized_address(entity, value)
        elif item.target_field != "*":
            setattr(entity, item.target_field, value)
        self.session.add(entity); self.session.flush()
        self._provenance(run, item, entity)

    def _apply_host_address(self, app, host: cm.HostRecord, value: object) -> None:
        address = self.session.get(cm.Address, host.address_id) if host.address_id else None
        if address is None:
            address = cm.Address(application_id=app.id, context="host", owner_id=host.id)
            self.session.add(address)
            self.session.flush()
            host.address_id = address.id
        self._apply_normalized_address(address, value)

    @staticmethod
    def _apply_normalized_address(entity: cm.Address, value: object) -> None:
        parsed = normalize_address(value)
        entity.unstructured_source_text = parsed.raw
        for field, parsed_value in {
            "unit": parsed.unit,
            "street_number": parsed.street_number,
            "street_name": parsed.street_name,
            "city": parsed.city,
            "state_province": parsed.province_or_state,
            "postal_code": parsed.postal_code,
            "country_code": parsed.country_code,
        }.items():
            if parsed_value and not getattr(entity, field):
                setattr(entity, field, parsed_value)
        entity.review_state = "needs_review"

    @staticmethod
    def _candidate_apply_error(
        item: cm.CanadaImportCandidate, error: Exception
    ) -> DomainValidationError:
        category = (
            "database_invariant" if isinstance(error, IntegrityError)
            else "field_validation" if isinstance(error, (DomainValidationError, DomainNotFound))
            else "persistence_failure"
        )
        explanation = (
            str(error) if isinstance(error, (DomainValidationError, DomainNotFound))
            else "The value violates a canonical data constraint."
        )
        message = f"{item.target_label} could not be applied. {explanation}"
        failure = DomainValidationError(message)
        value = item.proposed_value_json
        safe_value = value if isinstance(value, (str, int, float, bool, type(None))) else None
        if isinstance(safe_value, str):
            safe_value = safe_value[:255]
        failure.api_detail = {
            "category": category,
            "code": "IMPORT_FIELD_INVALID",
            "section": item.domain_section,
            "field_path": item.source_path,
            "entity_id": str(item.target_entity_id) if item.target_entity_id else None,
            "message": message,
            "rejected_value": safe_value,
            "suggested_correction": "Edit or reject the proposed value, then apply the import again.",
            "retryable": True,
            "issues": [{
                "message": "The complete Apply transaction was rolled back.",
                "field_path": item.source_path,
            }],
        }
        return failure

    def _create_imported_applicant(self, run, app, accepted):
        first = next((
            item.proposed_value_json for item in accepted
            if item.source_path == "identity.given_names"
        ), None)
        last = next((
            item.proposed_value_json for item in accepted
            if item.source_path == "identity.family_name"
        ), None)
        if not first or not last:
            raise DomainValidationError(
                "Applicant identity is incomplete. Review the given and family name before applying this import."
            )
        person = models.Person(
            case_id=run.case_id,
            first_name=str(first),
            last_name=str(last),
            roles=["applicant"],
        )
        self.session.add(person)
        self.session.flush()
        app.applicant_person_id = person.id
        self.session.add(cm.CasePersonRole(
            case_id=run.case_id,
            person_id=person.id,
            role=cm.OperationalRole.APPLICANT,
            assigned_by=run.imported_by,
        ))
        self.session.flush()
        for item in accepted:
            if item.target_entity_type == "person" and item.target_entity_id is None:
                item.target_entity_id = person.id

    @staticmethod
    def _family_key(item: cm.CanadaImportCandidate) -> str:
        if item.source_record_key != "scalar":
            return item.source_record_key
        return "former_spouse" if (
            "former_" in item.source_path or "previous_" in item.source_path
        ) else "spouse"

    def _ensure_family_targets(self, run, app, accepted):
        """Create canonical relatives only when a complete human identity is accepted."""
        groups: dict[str, list[cm.CanadaImportCandidate]] = {}
        for item in accepted:
            if item.target_entity_type in {"family_person", "family_biography", "family_relationship"}:
                groups.setdefault(self._family_key(item), []).append(item)
        usable = list(accepted)
        for rel_key, items in groups.items():
            relationship = self._linked_family_relationship(run, rel_key)
            if relationship is not None:
                person = self.session.get(models.Person, relationship.related_person_id)
                for item in items:
                    if item.target_entity_type == "family_person":
                        item.target_entity_id = person.id
                    elif item.target_entity_type == "family_relationship":
                        item.target_entity_id = relationship.id
                continue
            first = next((item.proposed_value_json for item in items if item.target_entity_type == "family_person" and item.target_field == "first_name"), None)
            last = next((item.proposed_value_json for item in items if item.target_entity_type == "family_person" and item.target_field == "last_name"), None)
            if not str(first or "").strip() or not str(last or "").strip():
                for item in items:
                    item.status = "ambiguous"
                    item.conflict_type = "family_identity_incomplete"
                    if item in usable:
                        usable.remove(item)
                continue
            person = models.Person(
                case_id=run.case_id,
                first_name=str(first).strip(),
                last_name=str(last).strip(),
                roles=[cm.OperationalRole.OTHER.value],
            )
            self.session.add(person)
            self.session.flush()
            add_authoritative_role(
                self.session, person, cm.OperationalRole.OTHER, assigned_by=run.imported_by
            )
            kind = rel_key.split(":", 1)[0]
            parent_part = rel_key.split(":", 2)[1] if rel_key.startswith("parent:") else None
            parent_type = parent_part if parent_part in {"mother", "father"} else None
            relationship = cm.FamilyRelationship(
                application_id=app.id,
                applicant_person_id=app.applicant_person_id,
                related_person_id=person.id,
                relationship_type=kind,
                parent_type=parent_type,
                is_current=kind == cm.FamilyRelationshipType.SPOUSE,
                sort_order=self._next_order(cm.FamilyRelationship, app.id),
            )
            self.session.add(relationship)
            self.session.flush()
            self._link(run, rel_key, "family_relationship", relationship.id)
            self._link(run, rel_key, "family_person", person.id)
            for item in items:
                if item.target_entity_type == "family_person":
                    item.target_entity_id = person.id
                elif item.target_entity_type == "family_relationship":
                    item.target_entity_id = relationship.id
        return usable

    def _model(self, entity_type):
        return {"person":models.Person, "family_person":models.Person, "person_biography":cm.PersonBiography,
                "family_biography":cm.PersonBiography, "citizenship":cm.PersonCitizenship,
                "person_identifier":cm.PersonIdentifier,
                "residence":cm.ApplicantResidence, "travel_document":cm.TravelDocument,
                "contact":cm.ContactPoint, "address":cm.Address, "trip_plan":cm.TripPlan,
                "funding_source":cm.FundingSource, "host":cm.HostRecord,
                "family_relationship":cm.FamilyRelationship, "education":cm.EducationRecord,
                "activity":cm.ActivityRecord, "residence_history":cm.ResidenceHistoryRecord,
                "travel_history":cm.TravelHistoryRecord, "official_answer":cm.OfficialApplicationAnswer,
                "representative_authorization":cm.RepresentativeAuthorization,
                "application":cm.CanadaApplication}.get(entity_type)

    def _create_target(self, run, app, item, value):
        et, key = item.target_entity_type, item.source_record_key
        applicant_id = app.applicant_person_id
        if et == "person":
            return self.session.get(models.Person, applicant_id)
        if et == "person_biography": return self.session.get(cm.PersonBiography, applicant_id) or cm.PersonBiography(person_id=applicant_id)
        if et == "citizenship": return cm.PersonCitizenship(person_id=applicant_id, country_code=str(value), is_primary=item.source_path.endswith("nationality"), sort_order=0 if item.source_path.endswith("nationality") else 1)
        if et == "person_identifier": return self.session.scalar(select(cm.PersonIdentifier).where(cm.PersonIdentifier.person_id == applicant_id, cm.PersonIdentifier.identifier_type == "national_identity")) or cm.PersonIdentifier(person_id=applicant_id, identifier_type="national_identity", value=str(value) if item.target_field == "value" else "PENDING-REVIEW", country_code=str(value) if item.target_field == "country_code" else "UNK")
        if et == "residence":
            existing = self.session.scalar(select(cm.ApplicantResidence).where(cm.ApplicantResidence.application_id == app.id, cm.ApplicantResidence.is_current.is_(True)))
            return existing or cm.ApplicantResidence(application_id=app.id, country_code=str(value) if item.target_field == "country_code" else "UNK", is_current=True)
        if et == "travel_document":
            existing = self.session.scalar(select(cm.TravelDocument).where(cm.TravelDocument.application_id == app.id, cm.TravelDocument.is_primary.is_(True)))
            return existing or cm.TravelDocument(application_id=app.id, person_id=applicant_id, number=str(value) if item.target_field == "number" else "PENDING-REVIEW", issuing_country_code=str(value) if item.target_field == "issuing_country_code" else "UNK", is_primary=True, sort_order=0)
        if et == "contact":
            kind = "email" if item.source_path.endswith("email") else "phone"
            existing = self.session.scalar(select(cm.ContactPoint).where(cm.ContactPoint.person_id == applicant_id, cm.ContactPoint.type == kind, cm.ContactPoint.is_primary.is_(True)))
            return existing or cm.ContactPoint(person_id=applicant_id, type=kind, value=str(value), purpose="primary", is_primary=True, sort_order=0)
        if et == "address":
            if item.source_path.startswith(("family.", "relationships.")):
                rel_key = item.source_record_key if item.source_record_key != "scalar" else "spouse"
                relationship = self._linked_family_relationship(run, rel_key)
                if relationship is None: raise DomainValidationError("family relationship must be accepted before its address")
                existing = self.session.get(cm.Address, relationship.address_id) if relationship.address_id else None
                if existing: return existing
                address = cm.Address(application_id=app.id, context="family_member", owner_id=relationship.id)
                self.session.add(address); self.session.flush(); relationship.address_id = address.id
                return address
            context = "mailing" if "mailing" in item.source_path else "residential"
            existing = self.session.scalar(select(cm.Address).where(cm.Address.application_id == app.id, cm.Address.context == context, cm.Address.owner_id == app.id))
            return existing or cm.Address(application_id=app.id, context=context, owner_id=app.id)
        if et == "trip_plan": return self.session.scalar(select(cm.TripPlan).where(cm.TripPlan.application_id == app.id)) or cm.TripPlan(application_id=app.id)
        trip = self.session.scalar(select(cm.TripPlan).where(cm.TripPlan.application_id == app.id))
        if et == "funding_source":
            if trip is None: trip = cm.TripPlan(application_id=app.id); self.session.add(trip); self.session.flush()
            return cm.FundingSource(trip_plan_id=trip.id, payer_kind="other", is_primary=True, sort_order=0)
        if et in {"family_person", "family_biography", "family_relationship"}:
            rel_key = self._family_key(item)
            rel = self._linked_family_relationship(run, rel_key)
            if rel is None:
                raise DomainValidationError(
                    "Family identity is incomplete. Review given and family names before applying this import."
                )
            if et == "family_relationship": return rel
            person = self.session.get(models.Person, rel.related_person_id)
            if et == "family_person": return person
            bio = self.session.get(cm.PersonBiography, person.id) or cm.PersonBiography(person_id=person.id)
            return bio
        if et in {"education", "activity", "residence_history", "travel_history"}:
            model = self._model(et); linked = self._linked_entity(run.case_id, et, key, model)
            if linked: return linked
            order = self._next_order(model, app.id)
            if et == "education": entity = model(application_id=app.id, person_id=applicant_id, sort_order=order, is_primary=order == 0)
            elif et == "activity": entity = model(application_id=app.id, person_id=applicant_id, sort_order=order, period_status="unknown")
            elif et == "residence_history": entity = model(application_id=app.id, person_id=applicant_id, sort_order=order, country_code="UNK", status_or_purpose="Pending review", start_date=date(1900,1,1), end_date=date(9999,12,31))
            else: entity = model(application_id=app.id, person_id=applicant_id, sort_order=order, country_code="UNK", purpose="Pending review", entry_date=date(1900,1,1), exit_date=date(9999,12,31))
            self.session.add(entity); self.session.flush(); self._link(run, key, et, entity.id); return entity
        if et == "official_answer":
            code = item.source_path.split(".",1)[1]
            return self.session.scalar(select(cm.OfficialApplicationAnswer).where(cm.OfficialApplicationAnswer.application_id == app.id, cm.OfficialApplicationAnswer.question_code == code)) or cm.OfficialApplicationAnswer(application_id=app.id, question_code=code, answer="unknown")
        if et == "representative_profile": return self._representative_target(run, item)
        if et == "representative_authorization":
            raise DomainValidationError("select and authorize a representative explicitly before importing authorization fields")
        if et == "application": return app
        if et == "host":
            existing = self.session.scalar(select(cm.HostRecord).where(cm.HostRecord.trip_plan_id == trip.id, cm.HostRecord.is_primary.is_(True))) if trip else None
            if existing:
                return existing
            if item.target_field != "party_name" or not str(item.conflict_type or "").startswith("resolved_host_"):
                raise DomainValidationError("host type must be explicitly resolved before creating a host")
            if trip is None: trip = cm.TripPlan(application_id=app.id); self.session.add(trip); self.session.flush()
            host_type = item.conflict_type.removeprefix("resolved_host_")
            if host_type == "person":
                parts = str(value or "").split()
                if len(parts) < 2:
                    raise DomainValidationError(
                        "A person host requires both given and family names. Edit the host name and retry."
                    )
                party = models.Person(
                    case_id=run.case_id,
                    first_name=" ".join(parts[:-1]),
                    last_name=parts[-1],
                    roles=[cm.OperationalRole.HOST.value],
                )
                self.session.add(party); self.session.flush()
                add_authoritative_role(
                    self.session, party, cm.OperationalRole.HOST, assigned_by=run.imported_by
                )
                host = cm.HostRecord(
                    trip_plan_id=trip.id, host_type="person", person_id=party.id,
                    is_primary=True, sort_order=0,
                )
            else:
                party = cm.Organization(case_id=run.case_id, legal_name=str(value), organization_type="host")
                self.session.add(party); self.session.flush()
                host = cm.HostRecord(trip_plan_id=trip.id, host_type="organization", organization_id=party.id, is_primary=True, sort_order=0)
            self.session.add(host); self.session.flush(); self._link(run, "host:primary", "host", host.id)
            return host
        raise DomainValidationError(f"unsupported import target: {et}")

    def _representative_target(self, run, item):
        name = f"Imported: {run.source_identifier}"
        profile = self.session.scalar(select(cm.RepresentativeProfile).where(cm.RepresentativeProfile.profile_name == name))
        if profile is None: profile = cm.RepresentativeProfile(profile_name=name); self.session.add(profile); self.session.flush()
        latest = self.session.scalar(select(cm.RepresentativeProfileRevision).where(cm.RepresentativeProfileRevision.profile_id == profile.id).order_by(cm.RepresentativeProfileRevision.revision_number.desc()))
        values = {key: getattr(latest, key) if latest else None for key in self._representative_fields()}
        target_field = {
            "organization": "organization_name", "country": "country_code",
            "postcode": "postal_code",
        }.get(item.target_field, item.target_field)
        values[target_field] = self._coerce_for_field(
            item.target_entity_type, item.target_field, item.proposed_value_json
        )
        if not values["family_name"] or not values["given_names"]:
            raise DomainValidationError(
                "Representative identity is incomplete. Review given and family names before applying."
            )
        if latest and all(getattr(latest, key) == values[key] for key in values): return latest
        revision = cm.RepresentativeProfileRevision(profile_id=profile.id, revision_number=(latest.revision_number + 1 if latest else 1), created_by=run.imported_by, **values)
        self.session.add(revision); self.session.flush(); return revision

    def _apply_representative_batch(self, run, items):
        name = f"Imported: {run.source_identifier}"
        profile = self.session.scalar(select(cm.RepresentativeProfile).where(cm.RepresentativeProfile.profile_name == name))
        if profile is None:
            profile = cm.RepresentativeProfile(profile_name=name)
            self.session.add(profile); self.session.flush()
        latest = self.session.scalar(select(cm.RepresentativeProfileRevision).where(cm.RepresentativeProfileRevision.profile_id == profile.id).order_by(cm.RepresentativeProfileRevision.revision_number.desc()))
        values = {key: getattr(latest, key) if latest else None for key in self._representative_fields()}
        aliases = {"organization":"organization_name", "country":"country_code", "postcode":"postal_code"}
        for item in items:
            values[aliases.get(item.target_field, item.target_field)] = self._coerce_for_field(
                item.target_entity_type, item.target_field, item.proposed_value_json
            )
        if not values["family_name"] or not values["given_names"]:
            raise DomainValidationError(
                "Representative identity is incomplete. Review given and family names before applying."
            )
        if latest and all(getattr(latest, key) == values[key] for key in values):
            return latest
        revision = cm.RepresentativeProfileRevision(
            profile_id=profile.id, revision_number=(latest.revision_number + 1 if latest else 1),
            created_by=run.imported_by, **values,
        )
        self.session.add(revision); self.session.flush()
        return revision

    @staticmethod
    def _representative_fields():
        return ["family_name","given_names","organization_name","unit","street_number","street_name","city","province","country_code","postal_code","phone_country_code","phone_number","email","category","membership_number","membership_province","other_category_details","supervising_lawyer","supervising_lawyer_membership"]

    def _coerce_for_field(self, entity_type, field, value):
        if (entity_type, field) in COUNTRY_CODE_TARGETS:
            text = str(value or "").strip()
            if text not in ISO_ALPHA3_CODES:
                raise DomainValidationError(
                    "Country value is not a supported ISO alpha-3 code. "
                    "Review the import value before applying."
                )
            return text
        if field in {"date_of_birth","issue_date","expiry_date","resident_since","arrival_date","departure_date","relationship_start_date","relationship_end_date","start_date","end_date","entry_date","exit_date","official_application_date"}: return _date(value)
        if field in {"accompanying_applicant","mailing_same_as_residential"}: return value if isinstance(value, bool) else _bool(value)
        if field in {"available_funds_amount","amount"}: return Decimal(str(value))
        if field == "address": return value
        return value

    def _next_order(self, model, app_id):
        maximum = self.session.scalar(select(func.max(model.sort_order)).where(model.application_id == app_id))
        return 0 if maximum is None else maximum + 1

    def _link(self, run, key, entity_type, entity_id):
        link = self.session.scalar(select(cm.LegacyImportEntityLink).where(cm.LegacyImportEntityLink.case_id == run.case_id, cm.LegacyImportEntityLink.source_type == run.source_type, cm.LegacyImportEntityLink.source_record_key == key, cm.LegacyImportEntityLink.canonical_entity_type == entity_type))
        if link: link.last_import_run_id = run.id
        else: self.session.add(cm.LegacyImportEntityLink(case_id=run.case_id, source_type=run.source_type, source_record_key=key, canonical_entity_type=entity_type, canonical_entity_id=entity_id, first_import_run_id=run.id, last_import_run_id=run.id))

    def _provenance(self, run, item, entity, *, review_state=None, reviewed_by=None):
        entity_type = {"family_person":"person", "family_biography":"person_biography"}.get(item.target_entity_type, item.target_entity_type)
        if entity_type not in {value.value for value in cm.ProvenanceEntityType}: return
        entity_id = getattr(entity, "id", getattr(entity, "person_id", None))
        now = datetime.now(timezone.utc)
        for old in self.session.scalars(select(cm.FieldProvenanceReview).where(cm.FieldProvenanceReview.case_id == run.case_id, cm.FieldProvenanceReview.entity_type == entity_type, cm.FieldProvenanceReview.entity_id == entity_id, cm.FieldProvenanceReview.field_key == item.target_field, cm.FieldProvenanceReview.superseded_at.is_(None))): old.superseded_at = now
        if review_state is None:
            review_state = "confirmed" if (
                item.source_classification == "applicant_direct"
                and item.review_policy == "safe_direct_batch"
                and item.conflict_type is None
            ) else "unreviewed"
        reviewed_at = now if review_state in {"confirmed", "corrected", "rejected"} else None
        self.session.add(cm.FieldProvenanceReview(
            case_id=run.case_id, entity_type=entity_type, entity_id=entity_id,
            field_key=item.target_field, source_type=item.source_classification,
            source_reference=item.source_reference, source_digest=run.source_hash,
            review_state=review_state, reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
        ))

    def _refresh_counts(self, run):
        counts = {key: 0 for key in ("new","same","conflict","ambiguous","accepted","rejected","applied")}
        for status, count in self.session.execute(select(cm.CanadaImportCandidate.status, func.count()).where(cm.CanadaImportCandidate.import_run_id == run.id).group_by(cm.CanadaImportCandidate.status)):
            counts[status] = count
        run.counts_json = counts
