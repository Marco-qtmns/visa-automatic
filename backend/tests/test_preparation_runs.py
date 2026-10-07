from __future__ import annotations

import hashlib
import io
import inspect
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app import models
from backend.app.api.canada_preparation import canada_form_generator_provider
from backend.app.api.core import generated_storage_provider
from backend.app.config.canada_form_adapter_mapping import ADAPTER_MAPPINGS
from backend.app.database import get_session
from backend.app.integrations.canada_forms import (
    ADAPTER_VERSION,
    GENERATOR_VERSION,
    GeneratedArtifactResult,
    LegacyCanadaFormGeneratorAdapter,
    continuation_required,
)
from backend.app.main import app
from backend.app.models import canada as cm
from backend.app.services.canada_preparation import CanonicalPreparationPayloadBuilder
from backend.app.services.core import DomainValidationError
from backend.app.services.preparation_runs import CanadaPreparationService
from backend.app.services.workflow import WorkflowService, WorkflowTransitionError
from backend.app.storage import StoredObject, StorageObjectNotFound
from backend.tests.test_canada_preparation import ready_case


class MemoryStorage:
    def __init__(self):
        self.values: dict[str, bytes] = {}
        self.saves = 0

    def save(self, source, *, max_bytes):
        content = source.read()
        if len(content) > max_bytes:
            raise ValueError("too large")
        key = uuid.uuid4().hex
        self.values[key] = content
        self.saves += 1
        return StoredObject(key, len(content))

    def open(self, key):
        if key not in self.values:
            raise StorageObjectNotFound("missing")
        return io.BytesIO(self.values[key])

    def exists(self, key):
        return key in self.values

    def delete(self, key):
        self.values.pop(key, None)


def artifact(kind: str) -> GeneratedArtifactResult:
    filename = {
        "imm5257": "IMM5257-DRAFT.pdf",
        "imm5707": "IMM5707-DRAFT.pdf",
        "imm5476": "IMM5476-DRAFT.pdf",
        "imm5257_continuation": "IMM5257-CONTINUATION-DRAFT.pdf",
    }[kind]
    return GeneratedArtifactResult(
        artifact_type=kind,
        filename=filename,
        mime_type="application/pdf",
        content=f"%PDF-1.7\nsynthetic {kind}".encode(),
        generator="synthetic-test-adapter",
        generator_version=GENERATOR_VERSION,
        template_identifier=f"synthetic/{filename}",
        template_hash=hashlib.sha256(filename.encode()).hexdigest(),
    )


class FakeAdapter:
    adapter_version = ADAPTER_VERSION
    generator_version = GENERATOR_VERSION

    def __init__(self, *, omit: str | None = None, fail: bool = False):
        self.omit = omit
        self.fail = fail
        self.calls = []

    def generate(self, payload):
        self.calls.append(payload)
        if self.fail:
            raise RuntimeError("sensitive internal generator detail")
        kinds = ["imm5257", "imm5707", "imm5476"]
        if continuation_required(payload):
            kinds.append("imm5257_continuation")
        return tuple(artifact(kind) for kind in kinds if kind != self.omit)


def test_adapter_contract_has_exact_138_explicit_mappings():
    assert len(ADAPTER_MAPPINGS) == 138
    assert len({item.audited_path for item in ADAPTER_MAPPINGS}) == 138
    assert all(item.payload_selector and item.legacy_destination and item.transformation for item in ADAPTER_MAPPINGS)
    assert all(item.supply_mode in {"direct", "derived"} for item in ADAPTER_MAPPINGS)


def test_case_generation_boundary_has_no_legacy_or_google_source_reader():
    import backend.app.integrations.canada_forms as adapter_module
    import backend.app.services.preparation_runs as service_module
    source = (inspect.getsource(adapter_module) + inspect.getsource(service_module)).casefold()
    forbidden = (
        "source_readers", "raw_response", "case_store", ".canada-case.json",
        ".canada-representative.json", "google forms", "verified csv",
    )
    assert all(token not in source for token in forbidden)


def test_generation_requires_ready_and_adapter_receives_only_payload(session):
    case, _applicant, _application, passport, _trip = ready_case(session)
    passport.number = ""
    session.commit()
    adapter = FakeAdapter()
    with pytest.raises(DomainValidationError, match="not preparation-ready"):
        CanadaPreparationService(session, MemoryStorage(), adapter).prepare(case.id, initiated_by="employee")
    assert adapter.calls == []

    passport.number = "SYN123456"
    session.commit()
    run = CanadaPreparationService(session, MemoryStorage(), adapter).prepare(case.id, initiated_by="employee")
    assert run.status == "succeeded"
    assert len(adapter.calls) == 1
    assert adapter.calls[0].__class__.__name__ == "CanonicalPreparationPayload"


def test_adapter_maps_identity_passport_address_trip_answers_and_representative(session):
    case, *_ = ready_case(session)
    payload = CanonicalPreparationPayloadBuilder(session).build(case.id)
    legacy = LegacyCanadaFormGeneratorAdapter.to_legacy_case(payload)
    assert (legacy.identity.family_name, legacy.identity.given_names) == ("Synthetic", "Amina")
    assert legacy.passport.number == "SYN123456" and legacy.passport.has_other_valid_passport == "No"
    assert legacy.contact.address == "1 Teststrasse Zurich ZH 8000 CHE"
    assert legacy.contact.mailing_same_as_residential == "Yes"
    assert legacy.trip.purpose == "Tourism" and legacy.trip.available_funds_cad == "5000"
    assert legacy.activities[0].position == "Analyst"
    assert legacy.official_review.tuberculosis_or_close_contact_last_two_years == "No"
    assert legacy.representative.family_name == "Representative"


def test_other_valid_passport_semantics_are_date_and_primary_aware(session):
    case, applicant, application, primary, _trip = ready_case(session)
    service = CanonicalPreparationPayloadBuilder(session)
    assert service.build(case.id).passport.has_other_valid_passport is False
    expired = cm.TravelDocument(
        application_id=application.id, person_id=applicant.id, document_type="passport",
        number="EXPIRED", issuing_country_code="CHE", issue_date=date(2010, 1, 1),
        expiry_date=date(2020, 1, 1), is_primary=False, sort_order=1,
    )
    session.add(expired); session.commit()
    assert service.build(case.id).passport.has_other_valid_passport is False
    other_person = models.Person(case_id=case.id, first_name="Other", last_name="Person", roles=["other"])
    session.add(other_person); session.flush()
    session.add(cm.TravelDocument(
        application_id=application.id, person_id=other_person.id, document_type="passport",
        number="OTHERPERSON", issuing_country_code="CHE", issue_date=date(2025, 1, 1),
        expiry_date=date(2035, 1, 1), is_primary=False, sort_order=2,
    )); session.commit()
    assert service.build(case.id).passport.has_other_valid_passport is False
    expired.expiry_date = date(2030, 1, 1); session.commit()
    payload = service.build(case.id)
    assert payload.passport.has_other_valid_passport is True
    assert payload.secondary_passports[0].number == "EXPIRED"
    legacy = LegacyCanadaFormGeneratorAdapter.to_legacy_case(payload)
    assert legacy.passport.has_other_valid_passport == "Yes"
    assert "EXPIRED" in legacy.passport.other_passport_details
    primary.is_primary = False; session.commit()
    with pytest.raises(DomainValidationError):
        service.build(case.id)


def test_continuation_conditions_come_only_from_payload(session):
    case, applicant, application, *_ = ready_case(session)
    builder = CanonicalPreparationPayloadBuilder(session)
    assert continuation_required(builder.build(case.id)) is False
    session.add(cm.ResidenceHistoryRecord(
        application_id=application.id, person_id=applicant.id, country_code="FRA",
        status_or_purpose="visitor", start_date=date(2024, 1, 1), end_date=date(2024, 2, 1),
        review_state="confirmed", sort_order=0,
    ))
    session.commit()
    assert continuation_required(builder.build(case.id)) is True
    storage = MemoryStorage()
    run = CanadaPreparationService(session, storage, FakeAdapter()).prepare(case.id, initiated_by="employee")
    assert {item.artifact_type for item in CanadaPreparationService(session, storage).artifacts(run.id)} == {
        "imm5257", "imm5707", "imm5476", "imm5257_continuation",
    }


def test_success_storage_hash_history_current_stale_and_irrelevant_change(session):
    case, applicant, *_ = ready_case(session)
    storage = MemoryStorage(); adapter = FakeAdapter()
    service = CanadaPreparationService(session, storage, adapter)
    first = service.prepare(case.id, initiated_by="employee")
    assert case.workflow_state is models.WorkflowState.PREPARE
    assert storage.saves == 3
    artifacts = service.artifacts(first.id)
    assert len(artifacts) == 3
    assert all(item.file_hash == hashlib.sha256(storage.values[item.storage_key]).hexdigest() for item in artifacts)
    assert all(item.template_hash and item.generator_version for item in artifacts)
    assert service.status(case.id).package_status == "current"
    session.add(models.Task(case_id=case.id, type="note", title="Audit-only", status="completed")); session.commit()
    assert service.status(case.id).package_status == "current"
    applicant.last_name = "Changed"; session.commit()
    assert service.status(case.id).package_status == "stale"
    assert len(adapter.calls) == 1  # status never auto-regenerates
    second = service.prepare(case.id, initiated_by="employee")
    assert second.id != first.id and len(service.list_runs(case.id)) == 2
    assert service.status(case.id).current_run.id == second.id


def test_missing_or_failed_manifest_never_becomes_current_and_preserves_history(session):
    case, *_ = ready_case(session)
    storage = MemoryStorage()
    service = CanadaPreparationService(session, storage, FakeAdapter())
    succeeded = service.prepare(case.id, initiated_by="employee")
    with pytest.raises(DomainValidationError, match="complete expected"):
        CanadaPreparationService(session, storage, FakeAdapter(omit="imm5476")).prepare(case.id, initiated_by="employee")
    runs = service.list_runs(case.id)
    assert runs[0].status == "failed" and runs[0].error_code == "artifact_manifest_invalid"
    assert runs[1].id == succeeded.id and service.status(case.id).package_status == "current"

    # A failure for a changed payload leaves the old package historical/stale.
    case.purpose = "Changed canonical purpose"; session.commit()
    # Purpose is not in the canonical payload; change an output field instead.
    application = session.query(cm.CanadaApplication).filter_by(case_id=case.id).one()
    application.preferred_language_code = "fr"; session.commit()
    with pytest.raises(DomainValidationError, match="generation failed"):
        CanadaPreparationService(session, storage, FakeAdapter(fail=True)).prepare(case.id, initiated_by="employee")
    assert service.status(case.id).package_status == "failed"
    with pytest.raises(WorkflowTransitionError, match="generated application package"):
        WorkflowService(session, storage).transition(case.id, models.WorkflowState.REVIEW, actor="employee")
    assert service.list_runs(case.id)[-1].id == succeeded.id


def test_missing_stored_file_is_integrity_error_and_review_gate_uses_current_run(session):
    case, *_ = ready_case(session)
    storage = MemoryStorage(); service = CanadaPreparationService(session, storage, FakeAdapter())
    run = service.prepare(case.id, initiated_by="employee")
    workflow = WorkflowService(session, storage)
    workflow.transition(case.id, models.WorkflowState.REVIEW, actor="employee")
    assert workflow.get_state(case.id) is models.WorkflowState.REVIEW
    artifact_model = service.artifacts(run.id)[0]
    storage.delete(artifact_model.storage_key)
    result = service.status(case.id)
    assert result.package_status == "integrity_error"
    assert workflow.get_state(case.id) is models.WorkflowState.PREPARE


def test_stale_review_ready_regress_but_submitted_is_terminal(session):
    for start_state in (models.WorkflowState.REVIEW, models.WorkflowState.READY):
        case, applicant, *_ = ready_case(session)
        storage = MemoryStorage(); service = CanadaPreparationService(session, storage, FakeAdapter())
        service.prepare(case.id, initiated_by="employee")
        case.workflow_state = start_state; session.commit()
        applicant.last_name += "Changed"; session.commit()
        assert service.status(case.id).package_status == "stale"
        assert WorkflowService(session, storage).get_state(case.id) is models.WorkflowState.PREPARE

    case, applicant, *_ = ready_case(session)
    storage = MemoryStorage(); service = CanadaPreparationService(session, storage, FakeAdapter())
    service.prepare(case.id, initiated_by="employee")
    case.workflow_state = models.WorkflowState.SUBMITTED; session.commit()
    applicant.last_name += "Changed"; session.commit()
    assert service.status(case.id).package_status == "submitted_discrepancy"
    assert WorkflowService(session, storage).get_state(case.id) is models.WorkflowState.SUBMITTED


def test_running_run_uniqueness_prevents_ambiguous_concurrency(session):
    case, *_ = ready_case(session)
    payload = CanonicalPreparationPayloadBuilder(session).build(case.id)
    session.add(models.PreparationRun(
        case_id=case.id, status="running", initiated_by="first",
        payload_schema_version=payload.schema_version, preparation_policy_version=payload.policy_version,
        payload_hash="a" * 64, adapter_version=ADAPTER_VERSION, generator_version=GENERATOR_VERSION,
    )); session.commit()
    with pytest.raises(DomainValidationError, match="already active"):
        CanadaPreparationService(session, MemoryStorage(), FakeAdapter()).prepare(case.id, initiated_by="second")


def test_api_status_prepare_history_content_and_no_storage_path(session):
    case, *_ = ready_case(session)
    storage = MemoryStorage(); adapter = FakeAdapter()
    def override_session():
        yield session
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[generated_storage_provider] = lambda: storage
    app.dependency_overrides[canada_form_generator_provider] = lambda: adapter
    client = TestClient(app)
    try:
        assert client.get(f"/cases/{case.id}/preparation").json()["package_status"] == "not_generated"
        response = client.post(f"/cases/{case.id}/prepare", json={"initiated_by": "employee"})
        assert response.status_code == 200
        body = response.json()
        assert "storage_key" not in str(body)
        status = client.get(f"/cases/{case.id}/preparation").json()
        assert status["package_status"] == "current"
        runs = client.get(f"/cases/{case.id}/preparation-runs").json()
        artifact_body = runs[0]["artifacts"][0]
        assert "storage_key" not in artifact_body
        content = client.get(f"/preparation-artifacts/{artifact_body['id']}/content")
        assert content.status_code == 200 and content.content.startswith(b"%PDF-")
        assert content.headers["content-disposition"].startswith("inline")
        actions = set(session.scalars(select(models.ApplicationAuditEvent.action)))
        assert {"PREPARATION_RUN_CREATED", "PREPARATION_GENERATION_COMPLETED", "PREPARATION_ARTIFACT_GENERATED"} <= actions
    finally:
        app.dependency_overrides.clear()


def test_real_legacy_adapter_generates_synthetic_official_form_package(session):
    case, *_ = ready_case(session)
    payload = CanonicalPreparationPayloadBuilder(session).build(case.id)
    generated = LegacyCanadaFormGeneratorAdapter().generate(payload)
    assert {item.artifact_type for item in generated} == {"imm5257", "imm5707", "imm5476"}
    assert all(item.content.startswith(b"%PDF-") and len(item.template_hash) == 64 for item in generated)
