from __future__ import annotations

import io
import uuid

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.api.core import quality_provider, storage_provider
from backend.app.database import get_session
from backend.app.main import app
from backend.app.models import (
    Document,
    DocumentQualityState,
    Requirement,
    RequirementDocumentMatch,
    RequirementFulfillmentSource,
    RequirementFulfillmentStatus,
    WorkflowState,
)
from backend.app.quality_evaluators import (
    QualityCheckFinding,
    TypeSpecificQualityResult,
)
from backend.app.schemas.core import QualityManualReview
from backend.app.services import DocumentQualityService, RequirementCompletenessService
from backend.app.storage import LocalStorageProvider


def pdf_bytes(text: str = "Synthetic quality fixture") -> bytes:
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), text)
    value = pdf.tobytes()
    pdf.close()
    return value


def png_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (80, 60), "white").save(stream, format="PNG")
    return stream.getvalue()


class SyntheticEvaluator:
    name = "synthetic_test"
    version = "1"

    def evaluate(self, content, checks):
        status = "manual_review" if "MANUAL_REVIEW" in content.text else "pass"
        coverage = []
        for month in ("2026-06", "2026-07", "2026-08"):
            if month in content.text:
                coverage.append(month)
        return TypeSpecificQualityResult(
            checks=[
                QualityCheckFinding(
                    check_id=check.check_id,
                    status=status,
                    evidence="Synthetic deterministic fixture",
                    issue="Employee confirmation required" if status == "manual_review" else None,
                    evaluator=self.name,
                )
                for check in checks
            ],
            extracted_metadata={"coverage_months": coverage} if coverage else {},
        )


@pytest.fixture
def quality_client(session, tmp_path):
    storage = LocalStorageProvider(tmp_path / "quality-storage")

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[storage_provider] = lambda: storage
    app.dependency_overrides[quality_provider] = lambda: SyntheticEvaluator()
    try:
        yield TestClient(app), storage
    finally:
        app.dependency_overrides.clear()


def create_case(client: TestClient, suffix: str):
    case = client.post(
        "/cases",
        json={"case_number": f"M7-{suffix}", "visa_type": "OTHER", "purpose": "synthetic"},
    ).json()
    person = client.post(
        f"/cases/{case['id']}/persons",
        json={"first_name": "Synthetic", "last_name": suffix, "roles": ["sponsor"]},
    ).json()
    return case, person


def create_requirement(client, case, person, *, policy=None):
    payload = {
        "document_type": "bank_statements",
        "owner_role": "sponsor",
        "owner_person_id": person["id"],
        "requirement_level": "required",
        "reason": "Synthetic evidence requirement",
        "is_blocking": True,
    }
    if policy is not None:
        payload["completeness_policy_json"] = policy
    response = client.post(f"/cases/{case['id']}/requirements", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, case, person=None, *, text="Synthetic", assigned=True, image=False):
    content = png_bytes() if image else pdf_bytes(text)
    data = {}
    if assigned:
        data = {"document_type": "bank_statements", "person_id": person["id"]}
    response = client.post(
        f"/cases/{case['id']}/documents/upload",
        data=data,
        files={"file": ("synthetic.png" if image else "synthetic.pdf", content, "image/png" if image else "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def match(client, requirement, document):
    response = client.post(
        f"/requirements/{requirement['id']}/documents/{document['id']}",
        json={"created_by": "test.employee"},
    )
    assert response.status_code == 201, response.text


def run_quality(client, document):
    response = client.post(f"/documents/{document['id']}/quality-check")
    assert response.status_code == 201, response.text
    return response.json()


def test_structured_quality_history_and_no_classification_or_matching_side_effects(quality_client):
    client, _ = quality_client
    case, person = create_case(client, "STRUCTURED")
    document = upload(client, case, person)

    first = run_quality(client, document)
    second = run_quality(client, document)
    history = client.get(f"/documents/{document['id']}/quality-checks").json()

    assert first["status"] == second["status"] == "passed"
    assert first["checks_json"][0] == {
        "check_id": "stored_file_accessible",
        "status": "pass",
        "evidence": first["checks_json"][0]["evidence"],
        "issue": None,
        "evaluator": "deterministic",
        "confidence": None,
    }
    assert len(history) == 2 and history[0]["id"] == second["id"]
    assert first["document_hash"] == second["document_hash"]
    reloaded = client.get(f"/documents/{document['id']}").json()
    assert reloaded["document_type"] == "bank_statements"
    assert reloaded["person_id"] == person["id"]
    assert client.get(f"/documents/{document['id']}/requirements").json() == []


def test_valid_pdf_and_image_technical_checks_and_type_specific_profile(quality_client):
    client, _ = quality_client
    case, person = create_case(client, "FORMATS")
    pdf = run_quality(client, upload(client, case, person))
    image = run_quality(client, upload(client, case, person, image=True))
    pdf_ids = {item["check_id"] for item in pdf["checks_json"]}
    image_ids = {item["check_id"] for item in image["checks_json"]}
    assert {"stored_file_accessible", "pdf_decodable", "bank_account_holder_confirmed", "bank_statement_period_confirmed"} <= pdf_ids
    assert {"stored_file_accessible", "image_decodable", "bank_account_holder_confirmed", "bank_statement_period_confirmed"} <= image_ids


def test_corrupt_pdf_fails_and_unassigned_document_gets_no_invented_type_pass(quality_client):
    client, _ = quality_client
    case, person = create_case(client, "FAILURE")
    corrupt = client.post(
        f"/cases/{case['id']}/documents/upload",
        data={"document_type": "bank_statements", "person_id": person["id"]},
        files={"file": ("corrupt.pdf", b"%PDF-1.4\nnot-a-real-pdf", "application/pdf")},
    ).json()
    failed = run_quality(client, corrupt)
    assert failed["status"] == "failed"
    assert any(item["check_id"] == "pdf_decodable" and item["status"] == "fail" for item in failed["checks_json"])

    unassigned = run_quality(client, upload(client, case, assigned=False))
    assert unassigned["status"] == "manual_review"
    assert [item["check_id"] for item in unassigned["checks_json"]][-1] == "document_type_assigned"
    assert not any(item["check_id"].startswith("bank_") for item in unassigned["checks_json"])


def test_manual_accept_and_reject_are_auditable_and_require_reason(quality_client):
    client, _ = quality_client
    case, person = create_case(client, "REVIEW")
    document = upload(client, case, person, text="MANUAL_REVIEW")
    check = run_quality(client, document)
    assert check["status"] == "manual_review"
    invalid = client.post(
        f"/documents/{document['id']}/quality-checks/{check['id']}/accept",
        json={"reviewed_by": "employee", "reason": ""},
    )
    assert invalid.status_code == 422
    accepted = client.post(
        f"/documents/{document['id']}/quality-checks/{check['id']}/accept",
        json={"reviewed_by": "employee", "reason": "Original verified"},
    ).json()
    assert accepted["review_decision"] == "accepted"
    assert accepted["reviewed_by"] == "employee"
    assert client.get(f"/documents/{document['id']}").json()["quality_status"] == "manual_accepted"
    new_check = run_quality(client, document)
    rejected = client.post(
        f"/documents/{document['id']}/quality-checks/{new_check['id']}/reject",
        json={"reviewed_by": "supervisor", "reason": "Required content is obscured"},
    ).json()
    assert rejected["review_decision"] == "rejected"
    assert client.get(f"/documents/{document['id']}").json()["quality_status"] == "manual_rejected"


def test_simple_completeness_requires_match_compatible_owner_and_acceptable_quality(quality_client, session):
    client, _ = quality_client
    case, person = create_case(client, "SIMPLE")
    requirement = create_requirement(client, case, person)
    document = upload(client, case, person)
    run_quality(client, document)
    assert client.get(f"/requirements/{requirement['id']}").json()["fulfillment_status"] == "pending"
    match(client, requirement, document)
    complete = client.post(f"/requirements/{requirement['id']}/evaluate-completeness").json()
    assert complete["status"] == "complete" and complete["accepted_count"] == 1
    current = client.get(f"/requirements/{requirement['id']}").json()
    assert current["fulfillment_status"] == "fulfilled"
    assert current["fulfillment_source"] == "automatic_document_evidence"

    # Historical/inconsistent matches are still rejected by completeness compatibility.
    other = client.post(
        f"/cases/{case['id']}/persons",
        json={"first_name": "Other", "last_name": "Owner", "roles": ["sponsor"]},
    ).json()
    wrong = upload(client, case, other)
    run_quality(client, wrong)
    session.add(RequirementDocumentMatch(
        requirement_id=uuid.UUID(requirement["id"]), document_id=uuid.UUID(wrong["id"])
    ))
    session.commit()
    result = client.post(f"/requirements/{requirement['id']}/evaluate-completeness").json()
    assert result["matched_count"] == 2 and result["accepted_count"] == 1


def test_failed_or_rejected_quality_cannot_fulfil_and_rejection_regresses(quality_client):
    client, _ = quality_client
    case, person = create_case(client, "REGRESSION")
    requirement = create_requirement(client, case, person)
    document = upload(client, case, person)
    match(client, requirement, document)
    check = run_quality(client, document)
    assert client.get(f"/requirements/{requirement['id']}").json()["fulfillment_status"] == "fulfilled"
    client.post(
        f"/documents/{document['id']}/quality-checks/{check['id']}/reject",
        json={"reviewed_by": "employee", "reason": "Evidence no longer qualifies"},
    )
    requirement_after = client.get(f"/requirements/{requirement['id']}").json()
    assert requirement_after["fulfillment_status"] == "pending"
    events = client.get(f"/requirements/{requirement['id']}/fulfillment-events").json()
    assert [(item["from_status"], item["to_status"]) for item in events] == [
        ("pending", "fulfilled"), ("fulfilled", "pending")
    ]


def test_month_coverage_uses_union_not_file_count_and_combined_pdf_can_complete(quality_client):
    client, _ = quality_client
    case, person = create_case(client, "COVERAGE")
    requirement = create_requirement(client, case, person, policy={
        "mode": "month_coverage", "required_months": ["2026-06", "2026-07", "2026-08"]
    })
    for _ in range(3):
        document = upload(client, case, person, text="2026-06")
        match(client, requirement, document)
        run_quality(client, document)
    partial = client.post(f"/requirements/{requirement['id']}/evaluate-completeness").json()
    assert partial["status"] == "incomplete"
    assert partial["coverage_json"]["covered_months"] == ["2026-06"]
    assert partial["missing_json"] == ["2026-07", "2026-08"]

    combined = upload(client, case, person, text="2026-06 2026-07 2026-08")
    match(client, requirement, combined)
    run_quality(client, combined)
    complete = client.post(f"/requirements/{requirement['id']}/evaluate-completeness").json()
    assert complete["status"] == "complete"
    assert complete["accepted_count"] == 4


def test_waiver_and_manual_fulfilment_are_not_overwritten(quality_client):
    client, _ = quality_client
    case, person = create_case(client, "PRESERVE")
    waived = create_requirement(client, case, person)
    response = client.patch(f"/requirements/{waived['id']}", json={
        "fulfillment_status": "waived", "waiver_reason": "Not applicable", "waived_by": "employee"
    })
    assert response.status_code == 200
    client.post(f"/requirements/{waived['id']}/evaluate-completeness")
    current = client.get(f"/requirements/{waived['id']}").json()
    assert current["fulfillment_status"] == "waived" and current["fulfillment_source"] == "waived"

    manual = create_requirement(client, case, person)
    client.patch(f"/requirements/{manual['id']}", json={"fulfillment_status": "fulfilled"})
    client.post(f"/requirements/{manual['id']}/evaluate-completeness")
    current = client.get(f"/requirements/{manual['id']}").json()
    assert current["fulfillment_status"] == "fulfilled" and current["fulfillment_source"] == "manual"


def test_match_removal_and_reactivation_trigger_reevaluation(quality_client):
    client, _ = quality_client
    case, person = create_case(client, "TRIGGERS")
    requirement = create_requirement(client, case, person)
    document = upload(client, case, person)
    match(client, requirement, document)
    run_quality(client, document)
    assert client.get(f"/requirements/{requirement['id']}").json()["fulfillment_status"] == "fulfilled"
    client.delete(f"/requirements/{requirement['id']}/documents/{document['id']}")
    assert client.get(f"/requirements/{requirement['id']}").json()["fulfillment_status"] == "pending"
    match(client, requirement, document)
    client.patch(f"/requirements/{requirement['id']}", json={"active": False})
    client.patch(f"/requirements/{requirement['id']}", json={"active": True})
    assert client.get(f"/requirements/{requirement['id']}").json()["fulfillment_status"] == "fulfilled"


def test_next_action_surfaces_quality_without_changing_workflow(quality_client, session):
    client, _ = quality_client
    case, person = create_case(client, "NEXT")
    requirement = create_requirement(client, case, person)
    document = upload(client, case, person)
    match(client, requirement, document)
    record = session.get(Document, uuid.UUID(document["id"]))
    record.classification_status = "confirmed"
    session.commit()
    for key in ("sponsor.exists", "host.exists"):
        response = client.post(f"/cases/{case['id']}/facts", json={
            "person_id": None,
            "key": key,
            "value_json": True,
            "source_type": "manual",
            "source_reference": "Synthetic test setup",
            "confidence": 1,
            "status": "confirmed",
        })
        assert response.status_code == 201
    before = client.get(f"/cases/{case['id']}").json()["workflow_state"]
    action = client.get(f"/cases/{case['id']}/next-action").json()
    after = client.get(f"/cases/{case['id']}").json()["workflow_state"]
    assert action["type"] == "REVIEW_DOCUMENT_QUALITY"
    assert action["document_id"] == document["id"]
    assert before == after == WorkflowState.INTAKE


def test_quality_api_exposes_understandable_completeness_history(quality_client):
    client, _ = quality_client
    case, person = create_case(client, "API")
    requirement = create_requirement(client, case, person)
    document = upload(client, case, person)
    match(client, requirement, document)
    check = run_quality(client, document)
    assert check["checks_json"] and check["provider"] == "synthetic_test"
    result = client.post(f"/requirements/{requirement['id']}/evaluate-completeness").json()
    history = client.get(f"/requirements/{requirement['id']}/completeness-evaluations").json()
    assert result["explanation"] == "At least one compatible matched document has acceptable quality"
    assert history[0]["status"] == "complete"
