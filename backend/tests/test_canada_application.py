from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient

from backend.app import models
from backend.app.models import canada as cm
from backend.app.schemas import canada as cs
from backend.app.services.canada import CanadaApplicationService
from backend.app.services.core import DomainValidationError
from backend.app.database import get_session
from backend.app.main import app as fastapi_app


def setup_case(session):
    case = models.Case(case_number=f"SYN-{uuid.uuid4().hex[:8]}", visa_type="canada_trv", purpose="Synthetic test")
    session.add(case)
    session.flush()
    people = [
        models.Person(case_id=case.id, first_name="Amina", last_name="Synthetic", roles=["applicant"]),
        models.Person(case_id=case.id, first_name="Carlos", last_name="Synthetic", roles=["other"]),
        models.Person(case_id=case.id, first_name="Sam", last_name="Synthetic", roles=["other"]),
    ]
    session.add_all(people)
    session.commit()
    return case, people


def setup_application(session):
    case, people = setup_case(session)
    service = CanadaApplicationService(session)
    app = service.create_application(case.id, cs.CanadaApplicationCreate(applicant_person_id=people[0].id))
    return service, case, people, app


def test_selected_applicant_is_explicit_and_unique(session):
    service, case, people, app = setup_application(session)
    assert service.selected_applicant(app.id).id == people[0].id
    service.assign_role(case.id, cs.RoleCreate(person_id=people[1].id, role="sponsor"))
    assert service.selected_applicant(app.id).id == people[0].id
    service.select_applicant(app.id, people[2].id, "employee@example.invalid")
    roles = list(session.scalars(select(cm.CasePersonRole).where(
        cm.CasePersonRole.case_id == case.id, cm.CasePersonRole.role == "applicant"
    )))
    assert len(roles) == 1
    assert roles[0].person_id == people[2].id

    app.applicant_person_id = None
    session.commit()
    with pytest.raises(DomainValidationError, match="explicitly"):
        service.selected_applicant(app.id)


def test_person_can_be_parent_and_sponsor_and_current_spouse_is_unique(session):
    service, case, people, app = setup_application(session)
    sponsor = service.assign_role(case.id, cs.RoleCreate(person_id=people[1].id, role="sponsor"))
    father = service.create_family_relationship(app.id, cs.FamilyRelationshipCreate(
        related_person_id=people[1].id, relationship_type="parent", parent_type="father", sort_order=0,
    ))
    assert sponsor.person_id == father.related_person_id
    service.create_family_relationship(app.id, cs.FamilyRelationshipCreate(
        related_person_id=people[2].id, relationship_type="spouse", is_current=True, sort_order=0,
    ))
    fourth = models.Person(case_id=case.id, first_name="Taylor", last_name="Synthetic", roles=["other"])
    session.add(fourth)
    session.commit()
    with pytest.raises(DomainValidationError, match="current spouse"):
        service.create_family_relationship(app.id, cs.FamilyRelationshipCreate(
            related_person_id=fourth.id, relationship_type="spouse", is_current=True, sort_order=1,
        ))


def test_child_and_activity_identity_survive_reorder(session):
    service, _case, people, app = setup_application(session)
    fourth = models.Person(case_id=app.case_id, first_name="Child", last_name="Two", roles=["child"])
    session.add(fourth)
    session.commit()
    first = service.create_family_relationship(app.id, cs.FamilyRelationshipCreate(
        related_person_id=people[1].id, relationship_type="child", sort_order=0,
    ))
    second = service.create_family_relationship(app.id, cs.FamilyRelationshipCreate(
        related_person_id=fourth.id, relationship_type="child", sort_order=1,
    ))
    reordered = service.reorder(cm.FamilyRelationship, app.id, [second.id, first.id])
    assert [item.id for item in reordered] == [second.id, first.id]
    assert [item.sort_order for item in reordered] == [0, 1]

    old = service.create_ordered_record(cm.ActivityRecord, app.id, cs.ActivityCreate(
        person_id=people[0].id, position="Past", period_status="completed", sort_order=0,
    ))
    current = service.create_ordered_record(cm.ActivityRecord, app.id, cs.ActivityCreate(
        person_id=people[0].id, position="Engineer", period_status="current", sort_order=1,
    ))
    service.reorder(cm.ActivityRecord, app.id, [current.id, old.id])
    assert session.get(cm.ActivityRecord, current.id).position == "Engineer"
    assert service.applicant_occupation(app.id) == "Engineer"


def test_primary_passport_and_host_constraints(session):
    service, case, people, app = setup_application(session)
    service.create_travel_document(app.id, cs.TravelDocumentCreate(
        person_id=people[0].id, number="P-SYN-1", issuing_country_code="CHE", is_primary=True, sort_order=0,
    ))
    with pytest.raises(DomainValidationError, match="primary passport"):
        service.create_travel_document(app.id, cs.TravelDocumentCreate(
            person_id=people[0].id, number="P-SYN-2", issuing_country_code="CHE", is_primary=True, sort_order=1,
        ))
    service.upsert_trip_plan(app.id, cs.TripPlanWrite())
    service.create_host(app.id, cs.HostCreate(host_type="person", person_id=people[1].id, is_primary=True, sort_order=0))
    with pytest.raises(DomainValidationError, match="primary host"):
        service.create_host(app.id, cs.HostCreate(host_type="person", person_id=people[2].id, is_primary=True, sort_order=1))
    with pytest.raises(ValueError, match="person host"):
        cs.HostCreate(host_type="person", organization_id=uuid.uuid4(), sort_order=2)


def test_purpose_unknown_answer_and_occupation_authority(session):
    service, _case, people, app = setup_application(session)
    plan = service.upsert_trip_plan(app.id, cs.TripPlanWrite(intake_purpose_text="Visit a friend"))
    assert plan.imm5257_purpose_code is None
    answer = service.upsert_official_answer(app.id, cs.OfficialAnswerWrite(question_code="background.criminality"))
    assert answer.answer == "unknown"
    biography = service.upsert_biography(people[0].id, cs.BiographyWrite(occupation_text="Biography value"))
    assert biography.occupation_text == "Biography value"
    assert service.applicant_occupation(app.id) is None
    service.create_ordered_record(cm.ActivityRecord, app.id, cs.ActivityCreate(
        person_id=people[0].id, position="Canonical activity", period_status="current", sort_order=0,
    ))
    assert service.person_occupation(app.id, people[0].id) == "Canonical activity"


def test_address_contexts_are_isolated(session):
    service, _case, _people, app = setup_application(session)
    residential = service.create_address(app.id, cs.AddressWrite(
        context="residential", owner_id=app.id, street_name="Alpha Street",
    ))
    mailing = service.create_address(app.id, cs.AddressWrite(
        context="mailing", owner_id=app.id, street_name="Alpha Street",
    ))
    service.update_address(residential.id, cs.AddressPatch(street_name="Changed Street"))
    assert session.get(cm.Address, residential.id).street_name == "Changed Street"
    assert session.get(cm.Address, mailing.id).street_name == "Alpha Street"


def test_representative_revision_is_immutable_for_authorization(session):
    service, case, people, app = setup_application(session)
    service.assign_role(case.id, cs.RoleCreate(person_id=people[1].id, role="representative"))
    profile, first = service.create_representative_profile(cs.RepresentativeProfileCreate(
        profile_name="Synthetic Representative",
        revision=cs.RepresentativeRevisionCreate(family_name="Original", given_names="Robin"),
    ))
    authorization = service.authorize_representative(app.id, cs.RepresentativeAuthorizationWrite(
        representative_person_id=people[1].id, profile_revision_id=first.id, action="appoint",
    ))
    second = service.revise_representative_profile(profile.id, cs.RepresentativeRevisionCreate(
        family_name="Updated", given_names="Robin",
    ))
    assert second.id != first.id
    assert authorization.profile_revision_id == first.id
    assert session.get(cm.RepresentativeProfileRevision, first.id).family_name == "Original"


def test_provenance_is_metadata_and_preserves_history(session):
    service, case, _people, app = setup_application(session)
    plan = service.upsert_trip_plan(app.id, cs.TripPlanWrite(intake_purpose_text="Typed value"))
    first = service.add_provenance(case.id, cs.ProvenanceCreate(
        entity_type="trip_plan", entity_id=plan.id, field_key="intake_purpose_text",
        source_type="manual", source_reference="synthetic:first",
    ))
    second = service.add_provenance(case.id, cs.ProvenanceCreate(
        entity_type="trip_plan", entity_id=plan.id, field_key="intake_purpose_text",
        source_type="document", source_reference="synthetic:second",
    ))
    assert session.get(cm.TripPlan, plan.id).intake_purpose_text == "Typed value"
    assert session.get(cm.FieldProvenanceReview, first.id).superseded_at is not None
    assert second.superseded_at is None


def test_canada_crud_api_and_bundle(session):
    case, people = setup_case(session)
    def override_session():
        yield session
    fastapi_app.dependency_overrides[get_session] = override_session
    client = TestClient(fastapi_app)
    try:
        created = client.post(f"/cases/{case.id}/canada-application", json={"applicant_person_id": str(people[0].id)})
        assert created.status_code == 201
        application_id = created.json()["id"]
        trip = client.put(f"/canada-applications/{application_id}/trip-plan", json={
            "intake_purpose_text": "Synthetic visit",
            "purpose_review_state": "unreviewed",
        })
        assert trip.status_code == 200
        answer = client.put(f"/canada-applications/{application_id}/official-answers/background.criminality", json={
            "question_code": "background.criminality", "answer": "unknown", "review_state": "unreviewed"
        })
        assert answer.status_code == 200
        bundle = client.get(f"/cases/{case.id}/canada-application/bundle")
        assert bundle.status_code == 200
        assert bundle.json()["trip_plan"]["intake_purpose_text"] == "Synthetic visit"
        assert bundle.json()["trip_plan"]["imm5257_purpose_code"] is None
        assert bundle.json()["official_answers"][0]["answer"] == "unknown"
    finally:
        fastapi_app.dependency_overrides.clear()
