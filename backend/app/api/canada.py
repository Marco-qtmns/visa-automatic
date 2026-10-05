from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ..database import get_session
from ..models import canada as cm
from ..schemas import canada as cs
from ..services.canada import CanadaApplicationService


router = APIRouter(tags=["Canada application"])
SessionDep = Annotated[Session, Depends(get_session)]


def service(session: Session) -> CanadaApplicationService:
    return CanadaApplicationService(session)


@router.post("/cases/{case_id}/canada-application", response_model=cs.CanadaApplicationRead, status_code=201)
def create_application(case_id: uuid.UUID, payload: cs.CanadaApplicationCreate, session: SessionDep):
    return service(session).create_application(case_id, payload)


@router.get("/cases/{case_id}/canada-application", response_model=cs.CanadaApplicationRead)
def get_application(case_id: uuid.UUID, session: SessionDep):
    return service(session).get_application(case_id)


@router.get("/cases/{case_id}/canada-application/bundle", response_model=cs.CanadaApplicationBundle)
def get_bundle(case_id: uuid.UUID, session: SessionDep):
    return service(session).bundle(case_id)


@router.patch("/canada-applications/{application_id}", response_model=cs.CanadaApplicationRead)
def update_application(application_id: uuid.UUID, payload: cs.CanadaApplicationUpdate, session: SessionDep):
    return service(session).update_application(application_id, payload)


@router.put("/canada-applications/{application_id}/applicant/{person_id}", response_model=cs.RoleRead)
def select_applicant(application_id: uuid.UUID, person_id: uuid.UUID, session: SessionDep):
    return service(session).select_applicant(application_id, person_id)


@router.post("/cases/{case_id}/operational-roles", response_model=cs.RoleRead, status_code=201)
def assign_role(case_id: uuid.UUID, payload: cs.RoleCreate, session: SessionDep):
    return service(session).assign_role(case_id, payload)


@router.put("/persons/{person_id}/biography", response_model=cs.BiographyRead)
def upsert_biography(person_id: uuid.UUID, payload: cs.BiographyWrite, session: SessionDep):
    return service(session).upsert_biography(person_id, payload)


@router.post("/cases/{case_id}/citizenships", response_model=cs.GenericRead, status_code=201)
def create_citizenship(case_id: uuid.UUID, payload: cs.CitizenshipCreate, session: SessionDep):
    return service(session).create_person_item(cm.PersonCitizenship, case_id, payload)


@router.post("/cases/{case_id}/identifiers", response_model=cs.GenericRead, status_code=201)
def create_identifier(case_id: uuid.UUID, payload: cs.IdentifierCreate, session: SessionDep):
    return service(session).create_person_item(cm.PersonIdentifier, case_id, payload)


@router.post("/cases/{case_id}/contacts", response_model=cs.GenericRead, status_code=201)
def create_contact(case_id: uuid.UUID, payload: cs.ContactPointCreate, session: SessionDep):
    return service(session).create_person_item(cm.ContactPoint, case_id, payload)


@router.post("/canada-applications/{application_id}/addresses", response_model=cs.GenericRead, status_code=201)
def create_address(application_id: uuid.UUID, payload: cs.AddressWrite, session: SessionDep):
    return service(session).create_address(application_id, payload)


@router.patch("/canada-addresses/{address_id}", response_model=cs.GenericRead)
def update_address(address_id: uuid.UUID, payload: cs.AddressPatch, session: SessionDep):
    return service(session).update_address(address_id, payload)


@router.post("/canada-applications/{application_id}/residences", response_model=cs.GenericRead, status_code=201)
def create_residence(application_id: uuid.UUID, payload: cs.ApplicantResidenceCreate, session: SessionDep):
    return service(session).create_residence(application_id, payload)


@router.post("/canada-applications/{application_id}/travel-documents", response_model=cs.GenericRead, status_code=201)
def create_travel_document(application_id: uuid.UUID, payload: cs.TravelDocumentCreate, session: SessionDep):
    return service(session).create_travel_document(application_id, payload)


@router.put("/canada-applications/{application_id}/trip-plan", response_model=cs.GenericRead)
def upsert_trip_plan(application_id: uuid.UUID, payload: cs.TripPlanWrite, session: SessionDep):
    return service(session).upsert_trip_plan(application_id, payload)


@router.post("/cases/{case_id}/organizations", response_model=cs.GenericRead, status_code=201)
def create_organization(case_id: uuid.UUID, payload: cs.OrganizationCreate, session: SessionDep):
    return service(session).create_organization(case_id, payload)


@router.post("/canada-applications/{application_id}/funding-sources", response_model=cs.GenericRead, status_code=201)
def create_funding_source(application_id: uuid.UUID, payload: cs.FundingSourceCreate, session: SessionDep):
    return service(session).create_funding_source(application_id, payload)


@router.post("/canada-applications/{application_id}/hosts", response_model=cs.GenericRead, status_code=201)
def create_host(application_id: uuid.UUID, payload: cs.HostCreate, session: SessionDep):
    return service(session).create_host(application_id, payload)


@router.post("/canada-applications/{application_id}/family-relationships", response_model=cs.GenericRead, status_code=201)
def create_family_relationship(application_id: uuid.UUID, payload: cs.FamilyRelationshipCreate, session: SessionDep):
    return service(session).create_family_relationship(application_id, payload)


@router.post("/canada-applications/{application_id}/education", response_model=cs.GenericRead, status_code=201)
def create_education(application_id: uuid.UUID, payload: cs.EducationCreate, session: SessionDep):
    return service(session).create_ordered_record(cm.EducationRecord, application_id, payload)


@router.post("/canada-applications/{application_id}/activities", response_model=cs.GenericRead, status_code=201)
def create_activity(application_id: uuid.UUID, payload: cs.ActivityCreate, session: SessionDep):
    return service(session).create_ordered_record(cm.ActivityRecord, application_id, payload)


@router.post("/canada-applications/{application_id}/residence-history", response_model=cs.GenericRead, status_code=201)
def create_residence_history(application_id: uuid.UUID, payload: cs.ResidenceHistoryCreate, session: SessionDep):
    return service(session).create_ordered_record(cm.ResidenceHistoryRecord, application_id, payload)


@router.post("/canada-applications/{application_id}/travel-history", response_model=cs.GenericRead, status_code=201)
def create_travel_history(application_id: uuid.UUID, payload: cs.TravelHistoryCreate, session: SessionDep):
    return service(session).create_ordered_record(cm.TravelHistoryRecord, application_id, payload)


@router.put("/canada-applications/{application_id}/collections/{collection}/order", response_model=list[cs.GenericRead])
def reorder_collection(application_id: uuid.UUID, collection: str, payload: cs.ReorderRequest, session: SessionDep):
    return service(session).reorder_collection(collection, application_id, payload.ordered_ids)


@router.delete("/canada-collections/{collection}/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collection_record(collection: str, record_id: uuid.UUID, session: SessionDep):
    service(session).delete_collection_record(collection, record_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/canada-applications/{application_id}/official-answers/{question_code}", response_model=cs.GenericRead)
def upsert_official_answer(application_id: uuid.UUID, question_code: str, payload: cs.OfficialAnswerWrite, session: SessionDep):
    if question_code != payload.question_code:
        from ..services.core import DomainValidationError
        raise DomainValidationError("question code path and payload must match")
    return service(session).upsert_official_answer(application_id, payload)


@router.put("/canada-applications/{application_id}/official-explanations/{section_code}", response_model=cs.GenericRead)
def upsert_official_explanation(application_id: uuid.UUID, section_code: str, payload: cs.OfficialExplanationWrite, session: SessionDep):
    if section_code != payload.section_code:
        from ..services.core import DomainValidationError
        raise DomainValidationError("section code path and payload must match")
    return service(session).upsert_official_explanation(application_id, payload)


@router.post("/representative-profiles", response_model=dict[str, Any], status_code=201)
def create_representative_profile(payload: cs.RepresentativeProfileCreate, session: SessionDep):
    profile, revision = service(session).create_representative_profile(payload)
    return {"profile": service(session)._row(profile), "revision": service(session)._row(revision)}


@router.post("/representative-profiles/{profile_id}/revisions", response_model=cs.GenericRead, status_code=201)
def revise_representative_profile(profile_id: uuid.UUID, payload: cs.RepresentativeRevisionCreate, session: SessionDep):
    return service(session).revise_representative_profile(profile_id, payload)


@router.put("/canada-applications/{application_id}/representative-authorization", response_model=cs.GenericRead)
def authorize_representative(application_id: uuid.UUID, payload: cs.RepresentativeAuthorizationWrite, session: SessionDep):
    return service(session).authorize_representative(application_id, payload)


@router.post("/cases/{case_id}/field-provenance", response_model=cs.GenericRead, status_code=201)
def add_provenance(case_id: uuid.UUID, payload: cs.ProvenanceCreate, session: SessionDep):
    return service(session).add_provenance(case_id, payload)
