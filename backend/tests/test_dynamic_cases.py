from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app import models
from backend.app.database import get_session
from backend.app.main import app
from backend.app.models import canada as cm


def client_for(session):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def create_case(client, suffix="BASE"):
    response = client.post("/cases", json={
        "case_number": f"PHASE-B-{suffix}", "visa_type": "TRV", "purpose": "To be confirmed",
    })
    assert response.status_code == 201, response.text
    return response.json()


def apply(client, case_id, decisions, reference="employee-ui"):
    history = client.get(f"/cases/{case_id}/canonical-revisions").json()
    revisions = {}
    for item in history:
        revisions[item["field_path"]] = max(revisions.get(item["field_path"], 0), item["revision"])
    response = client.post(f"/cases/{case_id}/canonical-decisions", json={
        "decisions": [{
            "field_path": path, "value_json": value,
            "expected_revision": revisions.get(path, 0),
        } for path, value in decisions],
        "source_type": "employee_manual", "source_reference": reference,
        "reviewed_by": "phase-b-test",
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_case_is_new_and_unknown_decisions_are_visible(session):
    client = client_for(session)
    try:
        case = create_case(client, "NEW")
        status = client.get(f"/cases/{case['id']}/dynamic-status")
        assert status.status_code == 200, status.text
        payload = status.json()
        assert payload["lifecycle_stage"] == "NEW"
        assert payload["can_enter_final_review"] is False
        assert {item["field_path"] for item in payload["issues"] if item["code"] == "unresolved_decision"} == {
            "sponsor.exists", "host.exists",
        }
    finally:
        app.dependency_overrides.clear()


def test_manual_intake_writes_typed_authority_revisions_and_dynamic_requirements(session):
    client = client_for(session)
    try:
        case = create_case(client, "MANUAL")
        sponsor = client.post(f"/cases/{case['id']}/persons", json={
            "first_name": "Sam", "last_name": "Sponsor", "roles": ["other"],
        }).json()
        revisions = apply(client, case["id"], [
            ("applicant.given_names", "Amina"),
            ("applicant.family_name", "Diallo"),
            ("contact.email", "amina@example.test"),
            ("trip.purpose", "Family visit"),
            ("sponsor.exists", True),
            ("sponsor.person_id", sponsor["id"]),
            ("host.exists", False),
            ("host.person_id", None),
            ("trip.payer", "sponsor"),
            ("destination.country_code", "CA"),
        ])
        assert len(revisions) == 10
        assert all(item["revision"] == 1 for item in revisions)
        case_id = uuid.UUID(case["id"])

        application = session.scalar(select(cm.CanadaApplication).where(cm.CanadaApplication.case_id == case_id))
        person = session.get(models.Person, application.applicant_person_id)
        assert (person.first_name, person.last_name) == ("Amina", "Diallo")
        assert application.applicant_person_id == person.id
        contact = session.scalar(select(cm.ContactPoint).where(cm.ContactPoint.person_id == person.id))
        assert contact.value == "amina@example.test"
        trip = session.scalar(select(cm.TripPlan).where(cm.TripPlan.application_id == application.id))
        assert trip.intake_purpose_text == "Family visit"
        sponsor_requirement = session.scalar(select(models.Requirement).where(
            models.Requirement.case_id == case_id,
            models.Requirement.rule_id == "TRV_SPONSOR_BANK_001",
        ))
        assert sponsor_requirement is not None and sponsor_requirement.active is True
        assert str(sponsor_requirement.owner_person_id) == sponsor["id"]

        status = client.get(f"/cases/{case['id']}/dynamic-status").json()
        assert status["lifecycle_stage"] == "ACTIVE"
        assert status["canonical_values"]["sponsor.exists"] is True
        assert status["canonical_values"]["sponsor.person_id"] == sponsor["id"]
        assert not any(item["field_path"] == "host.exists" for item in status["issues"])
    finally:
        app.dependency_overrides.clear()


def test_correction_keeps_immutable_revision_history(session):
    client = client_for(session)
    try:
        case = create_case(client, "REVISION")
        identity = [("applicant.given_names", "Amina"), ("applicant.family_name", "Diallo")]
        apply(client, case["id"], [*identity, ("trip.purpose", "Tourism")], "initial intake")
        apply(client, case["id"], [("trip.purpose", "Family visit")], "employee correction")
        history = client.get(f"/cases/{case['id']}/canonical-revisions").json()
        purpose = sorted(
            (item for item in history if item["field_path"] == "trip.purpose"),
            key=lambda item: item["revision"],
        )
        assert [(item["revision"], item["value_json"]) for item in purpose] == [
            (1, "Tourism"), (2, "Family visit"),
        ]
        assert purpose[1]["original_value_json"] == "Tourism"
        assert purpose[1]["review_state"] == "corrected"
    finally:
        app.dependency_overrides.clear()


def test_unknown_does_not_create_confirmed_fact_or_close_issue(session):
    client = client_for(session)
    try:
        case = create_case(client, "UNKNOWN")
        apply(client, case["id"], [
            ("applicant.given_names", "Amina"),
            ("applicant.family_name", "Diallo"),
            ("sponsor.exists", None),
        ])
        case_id = uuid.UUID(case["id"])
        confirmed = session.scalar(select(models.Fact).where(
            models.Fact.case_id == case_id, models.Fact.key == "sponsor.exists",
            models.Fact.status == "confirmed",
        ))
        assert confirmed is None
        status = client.get(f"/cases/{case['id']}/dynamic-status").json()
        assert any(item["field_path"] == "sponsor.exists" for item in status["issues"])
    finally:
        app.dependency_overrides.clear()


def test_stale_manual_update_cannot_overwrite_newer_canonical_value(session):
    client = client_for(session)
    try:
        case = create_case(client, "STALE")
        apply(client, case["id"], [
            ("applicant.given_names", "Amina"),
            ("applicant.family_name", "Diallo"),
            ("trip.purpose", "Tourism"),
        ])
        response = client.post(f"/cases/{case['id']}/canonical-decisions", json={
            "decisions": [{
                "field_path": "trip.purpose", "value_json": "Stale overwrite",
                "expected_revision": 0,
            }],
            "source_type": "employee_manual", "source_reference": "stale browser",
            "reviewed_by": "phase-b-test",
        })
        assert response.status_code == 409
        assert "stale canonical value" in response.json()["detail"]
        status = client.get(f"/cases/{case['id']}/dynamic-status").json()
        assert status["canonical_values"]["trip.purpose"] == "Tourism"
    finally:
        app.dependency_overrides.clear()
