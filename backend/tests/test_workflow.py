from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app.database import get_session
from backend.app.main import app
from backend.app.models import ApplicationAuditEvent, RequirementFulfillmentStatus, WorkflowState
from backend.app.schemas.core import (
    CaseCreate,
    DocumentCreate,
    FactCreate,
    RequirementCreate,
    RequirementUpdate,
    TaskCreate,
    TaskUpdate,
)
from backend.app.services import CoreDataService, WorkflowService, WorkflowTransitionError


def make_case(session, number="CA-WORKFLOW-001"):
    return CoreDataService(session).create_case(CaseCreate(
        case_number=number,
        visa_type="TRV",
        purpose="family_visit",
    ))


def add_fact(session, case_id, key, value, status="confirmed"):
    return CoreDataService(session).create_fact(case_id, FactCreate(
        key=key,
        value_json=value,
        source_type="manual",
        source_reference="synthetic workflow fixture",
        status=status,
    ))


def add_required_facts(session, case_id):
    add_fact(session, case_id, "sponsor.exists", True)
    add_fact(session, case_id, "host.exists", True)


def move_to_review(session, number="CA-WORKFLOW-REVIEW"):
    case = make_case(session, number)
    add_required_facts(session, case.id)
    workflow = WorkflowService(session)
    workflow.transition(case.id, WorkflowState.DOCUMENTS, actor="employee")
    workflow.transition(case.id, WorkflowState.PREPARE, actor="employee")
    # This general workflow fixture starts at REVIEW. M9D gate behavior is
    # covered with a canonical ready case and stored artifacts separately.
    case.workflow_state = WorkflowState.REVIEW
    session.commit()
    return case, workflow


def test_initial_state_is_intake_and_validated(session):
    case = make_case(session)
    assert case.workflow_state is WorkflowState.INTAKE
    assert WorkflowService(session).get_state(case.id) is WorkflowState.INTAKE


def test_intake_to_documents_requires_confirmed_structural_facts(session):
    case = make_case(session)
    workflow = WorkflowService(session)
    add_fact(session, case.id, "host.exists", False)
    with pytest.raises(WorkflowTransitionError, match="sponsor.exists"):
        workflow.transition(case.id, WorkflowState.DOCUMENTS)

    add_fact(session, case.id, "sponsor.exists", True, status="proposed")
    assert workflow.can_transition(case.id, WorkflowState.DOCUMENTS) is False
    with pytest.raises(WorkflowTransitionError, match="sponsor.exists"):
        workflow.transition(case.id, WorkflowState.DOCUMENTS)

    add_fact(session, case.id, "sponsor.exists", True)
    previous, updated, history = workflow.transition(
        case.id,
        WorkflowState.DOCUMENTS,
        actor="employee@example.test",
        reason="Synthetic intake confirmed",
    )
    assert previous is WorkflowState.INTAKE
    assert updated.workflow_state is WorkflowState.DOCUMENTS
    assert history.from_state is WorkflowState.INTAKE
    assert history.to_state is WorkflowState.DOCUMENTS
    assert history.actor == "employee@example.test"
    assert history.reason == "Synthetic intake confirmed"
    assert history.created_at is not None


def test_conflict_blocks_forward_progression_and_has_next_action_priority(session):
    case = make_case(session)
    add_fact(session, case.id, "sponsor.exists", False)
    conflict = add_fact(session, case.id, "sponsor.exists", True, status="conflict")
    workflow = WorkflowService(session)
    with pytest.raises(WorkflowTransitionError, match="conflicts"):
        workflow.transition(case.id, WorkflowState.DOCUMENTS)
    action = workflow.get_next_action(case.id)
    assert action.type == "RESOLVE_CONFLICT"
    assert action.fact_id == conflict.id
    assert action.fact_key == "sponsor.exists"


def test_invalid_transition_and_forbidden_regression_are_rejected(session):
    case = make_case(session)
    add_required_facts(session, case.id)
    workflow = WorkflowService(session)
    with pytest.raises(WorkflowTransitionError, match="not allowed"):
        workflow.transition(case.id, WorkflowState.REVIEW)
    workflow.transition(case.id, WorkflowState.DOCUMENTS)
    workflow.transition(case.id, WorkflowState.PREPARE)
    with pytest.raises(WorkflowTransitionError, match="not allowed"):
        workflow.transition(case.id, WorkflowState.INTAKE)


def test_documents_gate_uses_manual_fulfillment_and_waiver_audit(session):
    case = make_case(session)
    add_required_facts(session, case.id)
    core = CoreDataService(session)
    workflow = WorkflowService(session)
    workflow.transition(case.id, WorkflowState.DOCUMENTS)
    requirement = core.create_requirement(case.id, RequirementCreate(
        document_type="bank_statements",
        owner_role="sponsor",
        requirement_level="required",
        reason="Synthetic manual requirement",
        is_blocking=True,
    ))
    with pytest.raises(WorkflowTransitionError, match="blocking requirements"):
        workflow.transition(case.id, WorkflowState.PREPARE)
    with pytest.raises(ValueError, match="waiver_reason"):
        core.update_requirement(requirement.id, RequirementUpdate(
            fulfillment_status="waived"
        ))
    requirement = core.update_requirement(requirement.id, RequirementUpdate(
        fulfillment_status="waived",
        waiver_reason="Employee verified equivalent evidence",
        waived_by="employee@example.test",
    ))
    assert requirement.fulfillment_status is RequirementFulfillmentStatus.WAIVED
    assert requirement.waiver_reason == "Employee verified equivalent evidence"
    assert requirement.waived_by == "employee@example.test"
    assert requirement.waived_at is not None
    workflow.transition(case.id, WorkflowState.PREPARE)


def test_nonblocking_requirement_does_not_prevent_prepare(session):
    case = make_case(session)
    add_required_facts(session, case.id)
    workflow = WorkflowService(session)
    workflow.transition(case.id, WorkflowState.DOCUMENTS)
    CoreDataService(session).create_requirement(case.id, RequirementCreate(
        document_type="optional_letter",
        owner_role="applicant",
        requirement_level="supporting",
        reason="Synthetic non-blocking requirement",
        is_blocking=False,
    ))
    workflow.transition(case.id, WorkflowState.PREPARE)
    assert workflow.get_state(case.id) is WorkflowState.PREPARE


def test_prepare_to_review_rejects_old_temporary_evidence(session):
    case = make_case(session)
    add_required_facts(session, case.id)
    workflow = WorkflowService(session)
    workflow.transition(case.id, WorkflowState.DOCUMENTS)
    workflow.transition(case.id, WorkflowState.PREPARE)
    with pytest.raises(WorkflowTransitionError, match="generated application package"):
        workflow.transition(case.id, WorkflowState.REVIEW)
    CoreDataService(session).create_document(case.id, DocumentCreate(
        document_type="application_bundle",
        original_filename="synthetic-generated-bundle.pdf",
        storage_path="synthetic/cases/workflow/application-bundle.pdf",
        mime_type="application/pdf",
        source_type="generated",
    ))
    CoreDataService(session).create_task(case.id, TaskCreate(
        type="preparation_complete", title="Obsolete marker", status="completed"
    ))
    with pytest.raises(WorkflowTransitionError, match="generated application package"):
        workflow.transition(case.id, WorkflowState.REVIEW)
    assert workflow.get_state(case.id) is WorkflowState.PREPARE


def test_review_requires_explicit_actor_and_no_blocking_review_task(session):
    case, workflow = move_to_review(session)
    core = CoreDataService(session)
    blocking = core.create_task(case.id, TaskCreate(
        type="review_application",
        title="Review synthetic application",
        status="open",
        blocking=True,
    ))
    core.create_task(case.id, TaskCreate(
        type="review_note",
        title="Optional review note",
        status="open",
        blocking=False,
    ))
    with pytest.raises(WorkflowTransitionError, match="blocking review tasks"):
        workflow.transition(case.id, WorkflowState.READY, actor="reviewer")
    core.update_task(blocking.id, TaskUpdate(status="completed"))
    with pytest.raises(WorkflowTransitionError, match="actor"):
        workflow.transition(case.id, WorkflowState.READY)
    workflow.transition(case.id, WorkflowState.READY, actor="reviewer@example.test")
    assert workflow.get_state(case.id) is WorkflowState.READY


def test_ready_to_submitted_is_explicit_and_submitted_is_terminal(session):
    case, workflow = move_to_review(session, "CA-WORKFLOW-SUBMITTED")
    workflow.transition(case.id, WorkflowState.READY, actor="reviewer")
    assert workflow.get_state(case.id) is WorkflowState.READY
    workflow.transition(case.id, WorkflowState.SUBMITTED, actor="employee")
    assert workflow.get_state(case.id) is WorkflowState.SUBMITTED
    assert workflow.allowed_targets(case.id) == []
    with pytest.raises(WorkflowTransitionError, match="not allowed"):
        workflow.transition(case.id, WorkflowState.REVIEW)


def test_controlled_backward_transition_is_audited(session):
    case, workflow = move_to_review(session, "CA-WORKFLOW-REGRESSION")
    workflow.transition(
        case.id,
        WorkflowState.DOCUMENTS,
        actor="employee",
        reason="New sponsor evidence required",
    )
    history = workflow.history(case.id)
    assert history[-1].from_state is WorkflowState.REVIEW
    assert history[-1].to_state is WorkflowState.DOCUMENTS
    assert history[-1].reason == "New sponsor evidence required"


def test_next_action_priority_and_state_actions(session):
    core = CoreDataService(session)
    case = make_case(session, "CA-NEXT-ACTION")
    workflow = WorkflowService(session)
    assert workflow.get_next_action(case.id).fact_key == "sponsor.exists"
    add_required_facts(session, case.id)

    requirement = core.create_requirement(case.id, RequirementCreate(
        document_type="passport",
        owner_role="applicant",
        requirement_level="required",
        reason="Synthetic blocking requirement",
        is_blocking=True,
    ))
    action = workflow.get_next_action(case.id)
    assert action.type == "RESOLVE_REQUIREMENT"
    assert action.requirement_id == requirement.id
    core.update_requirement(requirement.id, RequirementUpdate(
        fulfillment_status="fulfilled"
    ))

    task = core.create_task(case.id, TaskCreate(
        type="confirm_details",
        title="Confirm synthetic details",
        status="open",
        blocking=True,
    ))
    action = workflow.get_next_action(case.id)
    assert action.type == "COMPLETE_TASK"
    assert action.task_id == task.id
    core.update_task(task.id, TaskUpdate(status="completed"))

    document = core.create_document(case.id, DocumentCreate(
        original_filename="unassigned.pdf",
        storage_path="synthetic/unassigned.pdf",
        mime_type="application/pdf",
        source_type="manual_upload",
    ))
    action = workflow.get_next_action(case.id)
    assert action.type == "ASSIGN_DOCUMENT"
    assert action.document_id == document.id


def test_next_action_review_ready_and_submitted(session):
    case, workflow = move_to_review(session, "CA-NEXT-STATES")
    assert workflow.get_next_action(case.id).type == "REVIEW_APPLICATION"
    workflow.transition(case.id, WorkflowState.READY, actor="reviewer")
    ready_action = workflow.get_next_action(case.id)
    assert ready_action.type == "SUBMIT_APPLICATION"
    assert ready_action.target_state is WorkflowState.SUBMITTED
    workflow.transition(case.id, WorkflowState.SUBMITTED, actor="employee")
    assert workflow.get_next_action(case.id).type == "NO_ACTION"


def test_workflow_api_and_direct_patch_prevention(session):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        case = client.post("/cases", json={
            "case_number": "CA-WORKFLOW-API",
            "visa_type": "TRV",
            "purpose": "family_visit",
        }).json()
        case_id = case["id"]
        direct_patch = client.patch(
            f"/cases/{case_id}", json={"workflow_state": "DOCUMENTS"}
        )
        assert direct_patch.status_code == 422
        for key in ("sponsor.exists", "host.exists"):
            response = client.post(f"/cases/{case_id}/facts", json={
                "key": key,
                "value_json": True,
                "source_type": "manual",
                "source_reference": "synthetic API fixture",
                "status": "confirmed",
            })
            assert response.status_code == 201
        transition = client.post(f"/cases/{case_id}/transition", json={
            "target_state": "DOCUMENTS",
            "actor": "employee@example.test",
            "reason": "Synthetic API transition",
        })
        assert transition.status_code == 200
        assert transition.json()["previous_state"] == "INTAKE"
        assert transition.json()["current_state"] == "DOCUMENTS"
        audit = session.scalar(select(ApplicationAuditEvent).where(
            ApplicationAuditEvent.action == "WORKFLOW_TRANSITION"
        ))
        assert audit is not None and audit.case_id.hex == case_id.replace("-", "")
        assert audit.metadata_json == {"from_state": "INTAKE", "to_state": "DOCUMENTS"}
        invalid = client.post(f"/cases/{case_id}/transition", json={
            "target_state": "REVIEW"
        })
        assert invalid.status_code == 409
        workflow = client.get(f"/cases/{case_id}/workflow")
        assert workflow.status_code == 200
        assert workflow.json()["history"][0]["reason"] == "Synthetic API transition"
        action = client.get(f"/cases/{case_id}/next-action")
        assert action.status_code == 200
        assert action.json()["type"] == "RESOLVE_REQUIREMENT"
        assert action.json()["requirement_id"] is not None
    finally:
        app.dependency_overrides.clear()
