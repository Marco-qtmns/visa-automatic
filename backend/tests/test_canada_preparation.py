from __future__ import annotations

import inspect
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import models
from backend.app.config.canada_preparation_policy import PAYLOAD_PROJECTIONS
from backend.app.database import get_session
from backend.app.main import app as fastapi_app
from backend.app.models import canada as cm
from backend.app.services.canada_preparation import (
    CanadaPreparationReadinessService,
    CanonicalPreparationPayloadBuilder,
    canonical_payload_bytes,
    canonical_payload_hash,
)
from backend.app.services.core import DomainValidationError
from backend.app.services.workflow import WorkflowService


def ready_case(session, *, state=models.WorkflowState.PREPARE):
    suffix = uuid.uuid4().hex[:8]
    case = models.Case(case_number=f"SYN-PREP-{suffix}", visa_type="canada_trv", purpose="Synthetic visit", workflow_state=state)
    session.add(case); session.flush()
    applicant = models.Person(case_id=case.id, first_name="Amina", last_name="Synthetic", roles=["applicant"])
    representative = models.Person(case_id=case.id, first_name="Rita", last_name="Representative", roles=["representative"])
    session.add_all([applicant, representative]); session.flush()
    app = cm.CanadaApplication(
        case_id=case.id, applicant_person_id=applicant.id,
        official_application_date=date(2026, 10, 15), application_date_review_state="confirmed",
        mailing_same_as_residential=True, preferred_language_code="en",
    )
    session.add(app); session.flush()
    session.add_all([
        cm.CasePersonRole(case_id=case.id, person_id=applicant.id, role="applicant", assigned_by="test"),
        cm.CasePersonRole(case_id=case.id, person_id=representative.id, role="representative", assigned_by="test"),
        cm.PersonBiography(person_id=applicant.id, date_of_birth=date(1992, 4, 17), sex="female", birth_city="Synthetic City", birth_country_code="CHE", marital_status="single"),
        cm.PersonCitizenship(person_id=applicant.id, country_code="CHE", is_primary=True, sort_order=0),
        cm.ApplicantResidence(application_id=app.id, country_code="CHE", immigration_status_code="citizen", is_current=True),
        cm.ContactPoint(person_id=applicant.id, type="email", value="amina@example.invalid", purpose="primary", is_primary=True, sort_order=0),
        cm.ContactPoint(person_id=applicant.id, type="phone", value="5550100", country_code="+41", purpose="primary", is_primary=True, sort_order=0),
        cm.Address(application_id=app.id, context="residential", owner_id=app.id, street_number="1", street_name="Teststrasse", city="Zurich", state_province="ZH", postal_code="8000", country_code="CHE", review_state="confirmed"),
    ])
    passport = cm.TravelDocument(application_id=app.id, person_id=applicant.id, document_type="passport", number="SYN123456", issuing_country_code="CHE", issue_date=date(2024, 1, 1), expiry_date=date(2034, 1, 1), is_primary=True, sort_order=0)
    trip = cm.TripPlan(application_id=app.id, intake_purpose_text="Visit friends", imm5257_purpose_code="Tourism", purpose_review_state="confirmed", arrival_date=date(2027, 1, 10), departure_date=date(2027, 1, 24), available_funds_amount=5000, available_funds_currency="CAD", funds_source_reference="Personal savings")
    session.add_all([passport, trip]); session.flush()
    session.add(cm.ActivityRecord(application_id=app.id, person_id=applicant.id, activity_type="employment", position="Analyst", organization_name="Synthetic AG", start_date=date(2020, 1, 1), period_status="current", city="Zurich", country_code="CHE", sort_order=0))
    for key, value in (("sponsor.exists", False), ("host.exists", False), ("trip.payer", "applicant")):
        session.add(models.Fact(case_id=case.id, person_id=applicant.id, key=key, value_json=value, source_type="manual", source_reference="test", status="confirmed"))
    from backend.app.config.canada_preparation_policy import OFFICIAL_QUESTION_CODES
    for code in OFFICIAL_QUESTION_CODES:
        session.add(cm.OfficialApplicationAnswer(application_id=app.id, question_code=code, answer="no", review_state="confirmed", reviewed_by="test"))
    profile = cm.RepresentativeProfile(profile_name=f"Synthetic profile {suffix}")
    session.add(profile); session.flush()
    revision = cm.RepresentativeProfileRevision(
        profile_id=profile.id, revision_number=1, family_name="Representative", given_names="Rita",
        street_name="Agency Street", city="Zurich", province="ZH", country_code="CHE", postal_code="8000",
        phone_number="5550199", email="rep@example.invalid", category="Unpaid - friend or family", created_by="test",
    )
    session.add(revision); session.flush()
    session.add(cm.RepresentativeAuthorization(application_id=app.id, representative_person_id=representative.id, profile_revision_id=revision.id, action="Appoint a representative", review_state="confirmed", reviewed_by="test"))
    session.commit()
    return case, applicant, app, passport, trip


def issue_paths(result):
    return {item.path for item in result.issues}


def test_complete_case_builds_versioned_immutable_deterministic_payload(session):
    case, *_ = ready_case(session)
    readiness = CanadaPreparationReadinessService(session).evaluate(case.id)
    assert readiness.ready and readiness.policy_version == "m9c-1" and readiness.schema_version == "m9d-1"
    payload = CanonicalPreparationPayloadBuilder(session).build(case.id)
    assert payload.schema_version == "m9d-1" and payload.policy_version == "m9c-1"
    assert canonical_payload_bytes(payload) == canonical_payload_bytes(CanonicalPreparationPayloadBuilder(session).build(case.id))
    assert readiness.payload_hash == canonical_payload_hash(payload) and len(readiness.payload_hash) == 64
    assert not any(hasattr(value, "_sa_instance_state") for value in payload.__dict__.values())
    with pytest.raises(ValidationError):
        payload.applicant.family_name = "Changed"


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    [
        (lambda values: setattr(values[1], "date_of_birth", None), "applicant.biography.date_of_birth"),
        (lambda values: setattr(values[2], "is_primary", False), "applicant.passport.primary"),
        (lambda values: setattr(values[3], "imm5257_purpose_code", None), "trip.imm5257_purpose_code"),
    ],
)
def test_required_applicant_passport_and_purpose_values_block(session, mutation, expected_path):
    case, applicant, app, passport, trip = ready_case(session)
    bio = session.get(cm.PersonBiography, applicant.id)
    mutation((app, bio, passport, trip)); session.commit()
    result = CanadaPreparationReadinessService(session).evaluate(case.id)
    assert not result.ready and expected_path in issue_paths(result)
    with pytest.raises(DomainValidationError):
        CanonicalPreparationPayloadBuilder(session).build(case.id)


def test_missing_and_invalid_applicant_selection_block(session):
    case = models.Case(case_number="SYN-NO-APP", visa_type="canada_trv", purpose="Visit")
    session.add(case); session.flush()
    session.add(cm.CanadaApplication(case_id=case.id, applicant_person_id=None))
    session.commit()
    result = CanadaPreparationReadinessService(session).evaluate(case.id)
    assert "application.applicant" in issue_paths(result)
    ready, applicant, app, *_ = ready_case(session)
    role = session.query(cm.CasePersonRole).filter_by(case_id=ready.id, role="applicant").one()
    session.delete(role); session.commit()
    assert "application.applicant" in issue_paths(CanadaPreparationReadinessService(session).evaluate(ready.id))


def test_provenance_review_import_and_fact_conflicts_block(session):
    case, applicant, app, passport, _trip = ready_case(session)
    provenance = cm.FieldProvenanceReview(case_id=case.id, entity_type="travel_document", entity_id=passport.id, field_key="number", source_type="legacy_derived", source_reference="synthetic", review_state="unreviewed")
    run = cm.CanadaLegacyImportRun(case_id=case.id, source_type="canada_case_json", source_identifier="synthetic.canada-case.json", source_hash="a" * 64, mapping_version="m9b-1", status="reviewing")
    session.add_all([provenance, run]); session.flush()
    session.add(cm.CanadaImportCandidate(import_run_id=run.id, domain_section="passport", employee_label="Passport number", target_entity_type="travel_document", target_entity_id=passport.id, target_field="number", source_path="passport.number", source_record_key="scalar", source_classification="legacy_derived", source_reference="synthetic", raw_value_json="OTHER", proposed_value_json="OTHER", current_value_json=passport.number, status="conflict", conflict_type="confirmed_canonical_value", review_policy="explicit_review", conflict_policy="manual_resolution"))
    session.add(models.Fact(case_id=case.id, person_id=applicant.id, key="host.exists", value_json=True, source_type="manual", source_reference="conflicting", status="conflict")); session.commit()
    result = CanadaPreparationReadinessService(session).evaluate(case.id)
    assert {"review_required", "unresolved_import_conflict", "unresolved_fact_conflict"} <= {item.code for item in result.issues}
    provenance.review_state = "confirmed"; session.commit()
    assert not any(item.path == "applicant.passport.number" and item.code == "review_required" for item in CanadaPreparationReadinessService(session).evaluate(case.id).issues)


def test_official_explanation_host_and_representative_conditionals(session):
    case, applicant, app, *_ = ready_case(session)
    answer = session.query(cm.OfficialApplicationAnswer).filter_by(application_id=app.id, question_code="committed_arrested_charged_or_convicted_any_country").one()
    answer.answer = "unknown"
    authorization = session.query(cm.RepresentativeAuthorization).filter_by(application_id=app.id).one()
    session.delete(authorization)
    host_fact = session.query(models.Fact).filter_by(case_id=case.id, key="host.exists", status="confirmed").one()
    host_fact.value_json = True; session.commit()
    result = CanadaPreparationReadinessService(session).evaluate(case.id)
    assert {"official_answers.committed_arrested_charged_or_convicted_any_country", "representative.authorization", "host.primary"} <= issue_paths(result)
    answer.answer = "yes"; session.commit()
    assert "official_explanations.criminal_details" in issue_paths(CanadaPreparationReadinessService(session).evaluate(case.id))


def test_host_contradiction_and_requirement_waiver(session):
    case, applicant, app, _passport, trip = ready_case(session)
    host = models.Person(case_id=case.id, first_name="Holly", last_name="Host", roles=["host"])
    requirement = models.Requirement(case_id=case.id, document_type="bank_statement", owner_role="applicant", owner_person_id=applicant.id, requirement_level="required", reason="Synthetic evidence", is_blocking=True, active=True, fulfillment_status=models.RequirementFulfillmentStatus.PENDING)
    session.add_all([host, requirement]); session.flush()
    session.add(cm.HostRecord(trip_plan_id=trip.id, host_type="person", person_id=host.id, is_primary=True, sort_order=0)); session.commit()
    result = CanadaPreparationReadinessService(session).evaluate(case.id)
    assert "host.primary" in issue_paths(result) and any(item.code == "blocking_requirement" for item in result.issues)
    requirement.fulfillment_status = models.RequirementFulfillmentStatus.WAIVED; requirement.waiver_reason = "Employee-approved synthetic waiver"; session.commit()
    assert not any(item.code == "blocking_requirement" for item in CanadaPreparationReadinessService(session).evaluate(case.id).issues)


def test_hash_changes_only_for_output_data_and_collection_order(session):
    case, applicant, app, *_ = ready_case(session)
    builder = CanonicalPreparationPayloadBuilder(session)
    first = canonical_payload_hash(builder.build(case.id))
    task = models.Task(case_id=case.id, type="note", title="Unrelated", description="Not generator input", status="completed", blocking=False)
    session.add(task); session.commit()
    assert canonical_payload_hash(builder.build(case.id)) == first
    applicant.last_name = "OutputChanged"; session.commit()
    second = canonical_payload_hash(builder.build(case.id)); assert second != first
    applicant.last_name = "Synthetic"
    activity = session.query(cm.ActivityRecord).filter_by(application_id=app.id).one()
    activity.period_status = "completed"; activity.end_date = date(2022, 1, 1); activity.sort_order = 1
    session.add(cm.ActivityRecord(application_id=app.id, person_id=applicant.id, activity_type="employment", position="Current role", start_date=date(2022, 2, 1), period_status="current", sort_order=0)); session.commit()
    ordered = canonical_payload_hash(builder.build(case.id))
    activities = session.query(cm.ActivityRecord).filter_by(application_id=app.id).order_by(cm.ActivityRecord.sort_order).all()
    activities[0].sort_order = -1; session.flush(); activities[1].sort_order = 0; session.flush(); activities[0].sort_order = 1; session.commit()
    assert canonical_payload_hash(builder.build(case.id)) != ordered


def test_projection_security_next_action_and_no_workflow_mutation(session):
    assert len(PAYLOAD_PROJECTIONS) == 138
    assert len({item.legacy_path for item in PAYLOAD_PROJECTIONS}) == 138
    assert all(item.payload_path and item.projection in {"source", "derived"} for item in PAYLOAD_PROJECTIONS)
    import backend.app.services.canada_preparation as module
    source = inspect.getsource(module)
    assert all(token not in source.casefold() for token in ("source_readers", "case_store", "pdf_drafts", "continuation", "google", ".canada-case.json", "not provided"))
    case, _applicant, _app, passport, _trip = ready_case(session)
    passport.number = ""; session.commit()
    before = case.workflow_state
    action = WorkflowService(session).get_next_action(case.id)
    session.refresh(case)
    assert action.type == "COMPLETE_PREPARATION_DATA"
    assert action.preparation_path == "applicant.passport.number"
    assert case.workflow_state == before


def test_readiness_api_returns_grouped_employee_issues(session):
    case, _applicant, _app, passport, _trip = ready_case(session)
    passport.number = ""; session.commit()
    def override_session():
        yield session
    fastapi_app.dependency_overrides[get_session] = override_session
    try:
        response = TestClient(fastapi_app).get(f"/cases/{case.id}/preparation-readiness")
        assert response.status_code == 200
        body = response.json()
        assert body["ready"] is False and body["policy_version"] == "m9c-1"
        assert body["sections"] and body["sections"][0]["issues"]
        policy = TestClient(fastapi_app).get("/canada-preparation-policy").json()
        assert policy["projection_count"] == 138
    finally:
        fastapi_app.dependency_overrides.clear()
