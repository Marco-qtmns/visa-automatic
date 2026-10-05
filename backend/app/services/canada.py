from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..models import canada as cm
from ..schemas import canada as cs
from .core import DomainNotFound, DomainValidationError


T = TypeVar("T")


PROVENANCE_MODELS: dict[str, type] = {
    "person": models.Person,
    "application": cm.CanadaApplication,
    "person_biography": cm.PersonBiography,
    "address": cm.Address,
    "residence": cm.ApplicantResidence,
    "travel_document": cm.TravelDocument,
    "trip_plan": cm.TripPlan,
    "funding_source": cm.FundingSource,
    "host": cm.HostRecord,
    "family_relationship": cm.FamilyRelationship,
    "education": cm.EducationRecord,
    "activity": cm.ActivityRecord,
    "residence_history": cm.ResidenceHistoryRecord,
    "travel_history": cm.TravelHistoryRecord,
    "official_answer": cm.OfficialApplicationAnswer,
    "official_explanation": cm.OfficialExplanation,
    "representative_authorization": cm.RepresentativeAuthorization,
}

COLLECTION_MODELS: dict[str, type] = {
    "family-relationships": cm.FamilyRelationship,
    "education": cm.EducationRecord,
    "activities": cm.ActivityRecord,
    "residence-history": cm.ResidenceHistoryRecord,
    "travel-history": cm.TravelHistoryRecord,
}


class CanadaApplicationService:
    """Authoritative writes for the canonical Canada application aggregate."""

    def __init__(self, session: Session):
        self.session = session

    def _get(self, model: type[T], object_id: uuid.UUID) -> T:
        value = self.session.get(model, object_id)
        if value is None:
            raise DomainNotFound(f"{model.__name__} not found")
        return value

    def _save(self, value: T) -> T:
        self.session.add(value)
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise DomainValidationError("record conflicts with existing Canada application data") from error
        self.session.refresh(value)
        return value

    def _application(self, application_id: uuid.UUID) -> cm.CanadaApplication:
        return self._get(cm.CanadaApplication, application_id)

    def _application_for_case(self, case_id: uuid.UUID) -> cm.CanadaApplication:
        value = self.session.scalar(select(cm.CanadaApplication).where(cm.CanadaApplication.case_id == case_id))
        if value is None:
            raise DomainNotFound("CanadaApplication not found")
        return value

    def _person_in_case(self, person_id: uuid.UUID, case_id: uuid.UUID) -> models.Person:
        person = self._get(models.Person, person_id)
        if person.case_id != case_id:
            raise DomainValidationError("person belongs to a different case")
        return person

    def _person_in_application(self, person_id: uuid.UUID, application: cm.CanadaApplication) -> models.Person:
        return self._person_in_case(person_id, application.case_id)

    @staticmethod
    def _changes(payload: BaseModel) -> dict[str, Any]:
        return payload.model_dump(exclude_unset=True, mode="python")

    def create_application(self, case_id: uuid.UUID, payload: cs.CanadaApplicationCreate) -> cm.CanadaApplication:
        self._get(models.Case, case_id)
        self._person_in_case(payload.applicant_person_id, case_id)
        if self.session.scalar(select(cm.CanadaApplication.id).where(cm.CanadaApplication.case_id == case_id)):
            raise DomainValidationError("case already has a Canada application")
        application = cm.CanadaApplication(case_id=case_id, applicant_person_id=payload.applicant_person_id)
        self.session.add(application)
        self.session.flush()
        self.session.add(cm.CasePersonRole(
            case_id=case_id, person_id=payload.applicant_person_id, role=cm.OperationalRole.APPLICANT,
        ))
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise DomainValidationError("could not create Canada application") from error
        self.session.refresh(application)
        return application

    def get_application(self, case_id: uuid.UUID) -> cm.CanadaApplication:
        return self._application_for_case(case_id)

    def update_application(self, application_id: uuid.UUID, payload: cs.CanadaApplicationUpdate) -> cm.CanadaApplication:
        value = self._application(application_id)
        if "legal_guardian_person_id" in payload.model_fields_set and payload.legal_guardian_person_id is not None:
            self._person_in_application(payload.legal_guardian_person_id, value)
            if payload.legal_guardian_person_id == value.applicant_person_id:
                raise DomainValidationError("applicant cannot be their own legal guardian")
        for key, item in self._changes(payload).items():
            setattr(value, key, item)
        return self._save(value)

    def selected_applicant(self, application_id: uuid.UUID) -> models.Person:
        application = self._application(application_id)
        if application.applicant_person_id is None:
            raise DomainValidationError("an applicant must be selected explicitly")
        role = self.session.scalar(select(cm.CasePersonRole).where(
            cm.CasePersonRole.case_id == application.case_id,
            cm.CasePersonRole.role == cm.OperationalRole.APPLICANT,
        ))
        if role is None or role.person_id != application.applicant_person_id:
            raise DomainValidationError("applicant selection is inconsistent")
        return self._person_in_case(application.applicant_person_id, application.case_id)

    def select_applicant(self, application_id: uuid.UUID, person_id: uuid.UUID, assigned_by: str | None = None) -> cm.CasePersonRole:
        application = self._application(application_id)
        self._person_in_application(person_id, application)
        role = self.session.scalar(select(cm.CasePersonRole).where(
            cm.CasePersonRole.case_id == application.case_id,
            cm.CasePersonRole.role == cm.OperationalRole.APPLICANT,
        ))
        if role is None:
            role = cm.CasePersonRole(case_id=application.case_id, person_id=person_id, role=cm.OperationalRole.APPLICANT)
        role.person_id = person_id
        role.assigned_by = assigned_by
        application.applicant_person_id = person_id
        self.session.add_all([application, role])
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise DomainValidationError("applicant selection conflicts with existing data") from error
        self.session.refresh(role)
        return role

    def assign_role(self, case_id: uuid.UUID, payload: cs.RoleCreate) -> cm.CasePersonRole:
        self._person_in_case(payload.person_id, case_id)
        if payload.role == cm.OperationalRole.APPLICANT:
            application = self._application_for_case(case_id)
            return self.select_applicant(application.id, payload.person_id, payload.assigned_by)
        return self._save(cm.CasePersonRole(case_id=case_id, **payload.model_dump()))

    def upsert_biography(self, person_id: uuid.UUID, payload: cs.BiographyWrite) -> cm.PersonBiography:
        self._get(models.Person, person_id)
        value = self.session.get(cm.PersonBiography, person_id) or cm.PersonBiography(person_id=person_id)
        for key, item in self._changes(payload).items():
            setattr(value, key, item)
        return self._save(value)

    def create_person_item(self, model: type[T], case_id: uuid.UUID, payload: BaseModel) -> T:
        person_id = payload.model_dump().get("person_id")
        self._person_in_case(person_id, case_id)
        if getattr(payload, "is_primary", False):
            existing = self.session.scalar(select(model).where(model.person_id == person_id, model.is_primary.is_(True)))
            if existing:
                raise DomainValidationError(f"person already has a primary {model.__name__}")
        return self._save(model(**payload.model_dump()))

    def create_address(self, application_id: uuid.UUID, payload: cs.AddressWrite) -> cm.Address:
        application = self._application(application_id)
        if payload.context in {cm.AddressContext.RESIDENTIAL, cm.AddressContext.MAILING}:
            if payload.owner_id != application.id:
                raise DomainValidationError("application addresses must be owned by the application")
        elif payload.context == cm.AddressContext.HOST:
            host = self._get(cm.HostRecord, payload.owner_id)
            if self._get(cm.TripPlan, host.trip_plan_id).application_id != application.id:
                raise DomainValidationError("host address owner belongs to a different application")
        elif payload.context == cm.AddressContext.FAMILY_MEMBER:
            relationship = self._get(cm.FamilyRelationship, payload.owner_id)
            if relationship.application_id != application.id:
                raise DomainValidationError("family address owner belongs to a different application")
        return self._save(cm.Address(application_id=application_id, **payload.model_dump()))

    def update_address(self, address_id: uuid.UUID, payload: cs.AddressPatch) -> cm.Address:
        value = self._get(cm.Address, address_id)
        for key, item in self._changes(payload).items():
            setattr(value, key, item)
        return self._save(value)

    def create_residence(self, application_id: uuid.UUID, payload: cs.ApplicantResidenceCreate) -> cm.ApplicantResidence:
        self.selected_applicant(application_id)
        if payload.is_current and self.session.scalar(select(cm.ApplicantResidence.id).where(
            cm.ApplicantResidence.application_id == application_id, cm.ApplicantResidence.is_current.is_(True)
        )):
            raise DomainValidationError("application already has a current residence")
        return self._save(cm.ApplicantResidence(application_id=application_id, **payload.model_dump()))

    def create_travel_document(self, application_id: uuid.UUID, payload: cs.TravelDocumentCreate) -> cm.TravelDocument:
        application = self._application(application_id)
        self._person_in_application(payload.person_id, application)
        if payload.is_primary and self.session.scalar(select(cm.TravelDocument.id).where(
            cm.TravelDocument.application_id == application_id, cm.TravelDocument.is_primary.is_(True)
        )):
            raise DomainValidationError("application already has a primary passport")
        return self._save(cm.TravelDocument(application_id=application_id, **payload.model_dump()))

    def upsert_trip_plan(self, application_id: uuid.UUID, payload: cs.TripPlanWrite) -> cm.TripPlan:
        self._application(application_id)
        value = self.session.scalar(select(cm.TripPlan).where(cm.TripPlan.application_id == application_id))
        value = value or cm.TripPlan(application_id=application_id)
        # The two purpose fields are independent; neither is inferred from the other.
        for key, item in self._changes(payload).items():
            setattr(value, key, item)
        return self._save(value)

    def create_organization(self, case_id: uuid.UUID, payload: cs.OrganizationCreate) -> cm.Organization:
        self._get(models.Case, case_id)
        return self._save(cm.Organization(case_id=case_id, **payload.model_dump()))

    def _trip(self, application_id: uuid.UUID) -> cm.TripPlan:
        value = self.session.scalar(select(cm.TripPlan).where(cm.TripPlan.application_id == application_id))
        if value is None:
            raise DomainValidationError("create the trip plan first")
        return value

    def create_funding_source(self, application_id: uuid.UUID, payload: cs.FundingSourceCreate) -> cm.FundingSource:
        application = self._application(application_id)
        trip = self._trip(application_id)
        if payload.person_id:
            self._person_in_application(payload.person_id, application)
        if payload.organization_id:
            org = self._get(cm.Organization, payload.organization_id)
            if org.case_id not in {None, application.case_id}:
                raise DomainValidationError("organization belongs to a different case")
        return self._save(cm.FundingSource(trip_plan_id=trip.id, **payload.model_dump()))

    def create_host(self, application_id: uuid.UUID, payload: cs.HostCreate) -> cm.HostRecord:
        application = self._application(application_id)
        trip = self._trip(application_id)
        if payload.person_id:
            self._person_in_application(payload.person_id, application)
        if payload.organization_id:
            org = self._get(cm.Organization, payload.organization_id)
            if org.case_id not in {None, application.case_id}:
                raise DomainValidationError("organization belongs to a different case")
        if payload.is_primary and self.session.scalar(select(cm.HostRecord.id).where(
            cm.HostRecord.trip_plan_id == trip.id, cm.HostRecord.is_primary.is_(True)
        )):
            raise DomainValidationError("trip already has a primary host")
        return self._save(cm.HostRecord(trip_plan_id=trip.id, **payload.model_dump()))

    def create_family_relationship(self, application_id: uuid.UUID, payload: cs.FamilyRelationshipCreate) -> cm.FamilyRelationship:
        application = self._application(application_id)
        applicant = self.selected_applicant(application_id)
        self._person_in_application(payload.related_person_id, application)
        if payload.related_person_id == applicant.id:
            raise DomainValidationError("family relationship cannot point to the applicant")
        existing_semantic = self.session.scalar(select(cm.FamilyRelationship).where(
            cm.FamilyRelationship.application_id == application_id,
            cm.FamilyRelationship.related_person_id == payload.related_person_id,
        ))
        if existing_semantic and existing_semantic.relationship_type != payload.relationship_type:
            raise DomainValidationError("person already has a contradictory family relationship")
        if payload.relationship_type == cm.FamilyRelationshipType.SPOUSE and payload.is_current:
            if self.session.scalar(select(cm.FamilyRelationship.id).where(
                cm.FamilyRelationship.application_id == application_id,
                cm.FamilyRelationship.relationship_type == cm.FamilyRelationshipType.SPOUSE,
                cm.FamilyRelationship.is_current.is_(True),
            )):
                raise DomainValidationError("application already has a current spouse")
        return self._save(cm.FamilyRelationship(
            application_id=application_id, applicant_person_id=applicant.id, **payload.model_dump()
        ))

    def create_ordered_record(self, model: type[T], application_id: uuid.UUID, payload: BaseModel) -> T:
        application = self._application(application_id)
        person_id = payload.model_dump().get("person_id")
        if person_id:
            self._person_in_application(person_id, application)
        return self._save(model(application_id=application_id, **payload.model_dump()))

    def reorder(self, model: type[T], application_id: uuid.UUID, ordered_ids: list[uuid.UUID]) -> list[T]:
        values = list(self.session.scalars(select(model).where(model.application_id == application_id)))
        by_id = {value.id: value for value in values}
        if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != set(by_id):
            raise DomainValidationError("reorder must contain every record exactly once")
        for index, record_id in enumerate(ordered_ids):
            by_id[record_id].sort_order = -(index + 1)
        self.session.flush()
        for index, record_id in enumerate(ordered_ids):
            by_id[record_id].sort_order = index
        # Employee ordering outranks the legacy source order on later imports.
        for link in self.session.scalars(select(cm.LegacyImportEntityLink).where(
            cm.LegacyImportEntityLink.canonical_entity_id.in_(ordered_ids)
        )):
            link.employee_order_locked = True
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise DomainValidationError("record ordering conflicts with existing data") from error
        return [by_id[item] for item in ordered_ids]

    def reorder_collection(self, collection: str, application_id: uuid.UUID, ordered_ids: list[uuid.UUID]) -> list[Any]:
        model = COLLECTION_MODELS.get(collection)
        if model is None:
            raise DomainValidationError("unsupported ordered collection")
        return self.reorder(model, application_id, ordered_ids)

    def delete_collection_record(self, collection: str, record_id: uuid.UUID) -> None:
        model = COLLECTION_MODELS.get(collection)
        if model is None:
            raise DomainValidationError("unsupported collection")
        value = self._get(model, record_id)
        self.session.delete(value)
        self.session.commit()

    def applicant_occupation(self, application_id: uuid.UUID) -> str | None:
        applicant = self.selected_applicant(application_id)
        activity = self.session.scalar(select(cm.ActivityRecord).where(
            cm.ActivityRecord.application_id == application_id,
            cm.ActivityRecord.person_id == applicant.id,
            cm.ActivityRecord.period_status == "current",
        ).order_by(cm.ActivityRecord.sort_order))
        # Applicant biography is deliberately not a fallback when current activity is absent.
        return activity.position if activity else None

    def person_occupation(self, application_id: uuid.UUID, person_id: uuid.UUID) -> str | None:
        application = self._application(application_id)
        self._person_in_application(person_id, application)
        if person_id == application.applicant_person_id:
            return self.applicant_occupation(application_id)
        biography = self.session.get(cm.PersonBiography, person_id)
        return biography.occupation_text if biography else None

    def upsert_official_answer(self, application_id: uuid.UUID, payload: cs.OfficialAnswerWrite) -> cm.OfficialApplicationAnswer:
        self._application(application_id)
        value = self.session.scalar(select(cm.OfficialApplicationAnswer).where(
            cm.OfficialApplicationAnswer.application_id == application_id,
            cm.OfficialApplicationAnswer.question_code == payload.question_code,
        )) or cm.OfficialApplicationAnswer(application_id=application_id, question_code=payload.question_code)
        for key, item in self._changes(payload).items():
            setattr(value, key, item)
        value.reviewed_at = (
            datetime.now(timezone.utc) if payload.review_state != cm.ReviewState.UNREVIEWED else None
        )
        return self._save(value)

    def upsert_official_explanation(self, application_id: uuid.UUID, payload: cs.OfficialExplanationWrite) -> cm.OfficialExplanation:
        self._application(application_id)
        value = self.session.scalar(select(cm.OfficialExplanation).where(
            cm.OfficialExplanation.application_id == application_id,
            cm.OfficialExplanation.section_code == payload.section_code,
        )) or cm.OfficialExplanation(application_id=application_id, section_code=payload.section_code)
        for key, item in self._changes(payload).items():
            setattr(value, key, item)
        value.reviewed_at = (
            datetime.now(timezone.utc) if payload.review_state != cm.ReviewState.UNREVIEWED else None
        )
        return self._save(value)

    def create_representative_profile(self, payload: cs.RepresentativeProfileCreate) -> tuple[cm.RepresentativeProfile, cm.RepresentativeProfileRevision]:
        profile = cm.RepresentativeProfile(profile_name=payload.profile_name)
        self.session.add(profile)
        self.session.flush()
        revision = cm.RepresentativeProfileRevision(
            profile_id=profile.id, revision_number=1, **payload.revision.model_dump()
        )
        self.session.add(revision)
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise DomainValidationError("representative profile conflicts with existing data") from error
        self.session.refresh(profile)
        self.session.refresh(revision)
        return profile, revision

    def revise_representative_profile(self, profile_id: uuid.UUID, payload: cs.RepresentativeRevisionCreate) -> cm.RepresentativeProfileRevision:
        self._get(cm.RepresentativeProfile, profile_id)
        number = self.session.scalar(select(func.max(cm.RepresentativeProfileRevision.revision_number)).where(
            cm.RepresentativeProfileRevision.profile_id == profile_id
        )) or 0
        return self._save(cm.RepresentativeProfileRevision(
            profile_id=profile_id, revision_number=number + 1, **payload.model_dump()
        ))

    def authorize_representative(self, application_id: uuid.UUID, payload: cs.RepresentativeAuthorizationWrite) -> cm.RepresentativeAuthorization:
        application = self._application(application_id)
        self._person_in_application(payload.representative_person_id, application)
        self._get(cm.RepresentativeProfileRevision, payload.profile_revision_id)
        role = self.session.scalar(select(cm.CasePersonRole).where(
            cm.CasePersonRole.case_id == application.case_id,
            cm.CasePersonRole.person_id == payload.representative_person_id,
            cm.CasePersonRole.role == cm.OperationalRole.REPRESENTATIVE,
        ))
        if role is None:
            raise DomainValidationError("authorized person must have the representative role")
        value = self.session.scalar(select(cm.RepresentativeAuthorization).where(
            cm.RepresentativeAuthorization.application_id == application_id
        )) or cm.RepresentativeAuthorization(application_id=application_id)
        for key, item in payload.model_dump().items():
            setattr(value, key, item)
        value.reviewed_at = (
            datetime.now(timezone.utc) if payload.review_state != cm.ReviewState.UNREVIEWED else None
        )
        return self._save(value)

    def add_provenance(self, case_id: uuid.UUID, payload: cs.ProvenanceCreate) -> cm.FieldProvenanceReview:
        self._get(models.Case, case_id)
        model = PROVENANCE_MODELS[payload.entity_type.value]
        entity = self._get(model, payload.entity_id)
        entity_case_id = self._entity_case_id(payload.entity_type.value, entity)
        if entity_case_id != case_id:
            raise DomainValidationError("provenance entity belongs to a different case")
        if payload.field_key not in inspect(model).columns:
            raise DomainValidationError("field_key is not a typed field on the entity")
        now = datetime.now(timezone.utc)
        current = list(self.session.scalars(select(cm.FieldProvenanceReview).where(
            cm.FieldProvenanceReview.case_id == case_id,
            cm.FieldProvenanceReview.entity_type == payload.entity_type,
            cm.FieldProvenanceReview.entity_id == payload.entity_id,
            cm.FieldProvenanceReview.field_key == payload.field_key,
            cm.FieldProvenanceReview.superseded_at.is_(None),
        )))
        for row in current:
            row.superseded_at = now
        value = cm.FieldProvenanceReview(case_id=case_id, **payload.model_dump())
        if payload.review_state != cm.ReviewState.UNREVIEWED:
            value.reviewed_at = now
        return self._save(value)

    def _entity_case_id(self, entity_type: str, entity: Any) -> uuid.UUID:
        if hasattr(entity, "case_id"):
            return entity.case_id
        if hasattr(entity, "application_id"):
            return self._application(entity.application_id).case_id
        if entity_type in {"funding_source", "host"}:
            return self._application(self._get(cm.TripPlan, entity.trip_plan_id).application_id).case_id
        if entity_type == "person_biography":
            return self._get(models.Person, entity.person_id).case_id
        raise DomainValidationError("cannot establish provenance entity ownership")

    @staticmethod
    def _row(value: Any) -> dict[str, Any]:
        return {column.key: getattr(value, column.key) for column in inspect(value.__class__).columns}

    def bundle(self, case_id: uuid.UUID) -> dict[str, Any]:
        app = self._application_for_case(case_id)
        trip = self.session.scalar(select(cm.TripPlan).where(cm.TripPlan.application_id == app.id))
        authorization = self.session.scalar(select(cm.RepresentativeAuthorization).where(
            cm.RepresentativeAuthorization.application_id == app.id
        ))
        people = list(self.session.scalars(select(models.Person.id).where(models.Person.case_id == case_id)))
        def rows(model, *conditions, order=None):
            statement = select(model).where(*conditions)
            if order is not None:
                statement = statement.order_by(order)
            return [self._row(item) for item in self.session.scalars(statement)]
        return {
            "application": self._row(app),
            "roles": rows(cm.CasePersonRole, cm.CasePersonRole.case_id == case_id),
            "biographies": rows(cm.PersonBiography, cm.PersonBiography.person_id.in_(people)),
            "citizenships": rows(cm.PersonCitizenship, cm.PersonCitizenship.person_id.in_(people), order=cm.PersonCitizenship.sort_order),
            "identifiers": rows(cm.PersonIdentifier, cm.PersonIdentifier.person_id.in_(people)),
            "contacts": rows(cm.ContactPoint, cm.ContactPoint.person_id.in_(people), order=cm.ContactPoint.sort_order),
            "addresses": rows(cm.Address, cm.Address.application_id == app.id),
            "applicant_residences": rows(cm.ApplicantResidence, cm.ApplicantResidence.application_id == app.id),
            "travel_documents": rows(cm.TravelDocument, cm.TravelDocument.application_id == app.id, order=cm.TravelDocument.sort_order),
            "trip_plan": self._row(trip) if trip else None,
            "funding_sources": rows(cm.FundingSource, cm.FundingSource.trip_plan_id == trip.id, order=cm.FundingSource.sort_order) if trip else [],
            "hosts": rows(cm.HostRecord, cm.HostRecord.trip_plan_id == trip.id, order=cm.HostRecord.sort_order) if trip else [],
            "organizations": rows(cm.Organization, cm.Organization.case_id == case_id),
            "family_relationships": rows(cm.FamilyRelationship, cm.FamilyRelationship.application_id == app.id, order=cm.FamilyRelationship.sort_order),
            "education": rows(cm.EducationRecord, cm.EducationRecord.application_id == app.id, order=cm.EducationRecord.sort_order),
            "activities": rows(cm.ActivityRecord, cm.ActivityRecord.application_id == app.id, order=cm.ActivityRecord.sort_order),
            "residence_history": rows(cm.ResidenceHistoryRecord, cm.ResidenceHistoryRecord.application_id == app.id, order=cm.ResidenceHistoryRecord.sort_order),
            "travel_history": rows(cm.TravelHistoryRecord, cm.TravelHistoryRecord.application_id == app.id, order=cm.TravelHistoryRecord.sort_order),
            "official_answers": rows(cm.OfficialApplicationAnswer, cm.OfficialApplicationAnswer.application_id == app.id),
            "official_explanations": rows(cm.OfficialExplanation, cm.OfficialExplanation.application_id == app.id),
            "representative_authorization": self._row(authorization) if authorization else None,
            "provenance": rows(cm.FieldProvenanceReview, cm.FieldProvenanceReview.case_id == case_id, order=cm.FieldProvenanceReview.created_at),
        }
