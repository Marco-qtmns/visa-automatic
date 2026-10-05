from __future__ import annotations

import io

import fitz
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app.api.core import classification_provider, storage_provider
from backend.app.classifiers import (
    ClassificationEvidenceItem,
    ClassifierResult,
    ExtractedDocumentContent,
    UnavailableDocumentClassifier,
    LocalTextDocumentClassifier,
    classifier_from_environment,
)
from backend.app.database import get_session
from backend.app.main import app
from backend.app import models
from backend.app.schemas import core as schemas
from backend.app.services import (
    CoreDataService,
    DocumentClassificationService,
    DocumentMatchingService,
    DocumentUploadService,
    DomainValidationError,
    WorkflowService,
)
from backend.app.storage import LocalStorageProvider


def synthetic_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    result = document.tobytes()
    document.close()
    return result


class FakeClassifier:
    name = "synthetic_fake"
    model_version = "test-v1"

    def __init__(self, result: ClassifierResult | None = None, error: Exception | None = None):
        self.result = result or ClassifierResult(
            document_type="bank_statements",
            owner_name="Carlos Silva",
            confidence=0.94,
            evidence=[
                ClassificationEvidenceItem("text", "Account holder: Carlos Silva"),
                ClassificationEvidenceItem("classification", "Bank transaction headings detected"),
            ],
        )
        self.error = error
        self.received: list[ExtractedDocumentContent] = []

    def classify(self, content: ExtractedDocumentContent) -> ClassifierResult:
        self.received.append(content)
        if self.error:
            raise self.error
        return self.result


def create_case_people_document(session, tmp_path, *, content: bytes | None = None, mime_type="application/pdf"):
    core = CoreDataService(session)
    case = core.create_case(schemas.CaseCreate(
        case_number="M6-SYNTHETIC", visa_type="TRV", purpose="Synthetic test"
    ))
    carlos = core.create_person(case.id, schemas.PersonCreate(
        first_name="Carlos", last_name="Silva", roles=["sponsor"]
    ))
    maria = core.create_person(case.id, schemas.PersonCreate(
        first_name="Maria", last_name="Silva", roles=["applicant"]
    ))
    storage = LocalStorageProvider(tmp_path / "classification-storage")
    payload = content or synthetic_pdf(
        "Synthetic Bank Statement\nAccount holder: Carlos Silva\nTransaction table"
    )
    document = DocumentUploadService(session, storage).upload(
        case.id,
        io.BytesIO(payload),
        original_filename="synthetic.pdf" if mime_type == "application/pdf" else "synthetic.jpg",
        declared_mime_type=mime_type,
    )
    return core, case, carlos, maria, document, storage


def test_structured_suggestion_pdf_extraction_owner_confidence_evidence_and_storage(
    session, tmp_path
):
    _core, _case, carlos, _maria, document, storage = create_case_people_document(session, tmp_path)
    classifier = FakeClassifier()
    result = DocumentClassificationService(session, storage, classifier).classify(document.id)

    assert result.status == models.ClassificationReviewStatus.SUGGESTED
    assert result.suggested_document_type == "bank_statements"
    assert result.suggested_person_id == carlos.id
    assert result.confidence == pytest.approx(0.94)
    assert len(result.evidence_json) >= 3
    assert result.provider == "synthetic_fake"
    assert result.model_version == "test-v1"
    assert len(result.document_hash) == 64
    assert "Synthetic Bank Statement" in classifier.received[0].text
    assert classifier.received[0].page_count == 1
    assert classifier.received[0].binary_content.startswith(b"%PDF-")
    assert session.get(models.Document, document.id).document_type is None
    assert session.get(models.Document, document.id).person_id is None


def test_explicit_local_text_provider_suggests_catalog_type(session, tmp_path):
    _core, _case, carlos, _maria, document, storage = create_case_people_document(session, tmp_path)
    result = DocumentClassificationService(
        session, storage, LocalTextDocumentClassifier()
    ).classify(document.id)
    assert result.suggested_document_type == "bank_statements"
    assert result.suggested_person_id == carlos.id
    assert result.provider == "local_text"


def test_unknown_type_is_normalized_confidence_is_clamped_and_no_owner_is_null(
    session, tmp_path
):
    _core, _case, _carlos, _maria, document, storage = create_case_people_document(session, tmp_path)
    classifier = FakeClassifier(ClassifierResult(
        document_type="invented-financial-proof",
        owner_name=None,
        confidence=4.2,
        evidence=[ClassificationEvidenceItem("classification", "Synthetic unsupported label")],
    ))
    result = DocumentClassificationService(session, storage, classifier).classify(document.id)
    assert result.suggested_document_type is None
    assert result.suggested_person_id is None
    assert result.confidence == 1.0
    assert any("catalog" in item["value"] for item in result.evidence_json)


def test_ambiguous_owner_is_not_guessed(session, tmp_path):
    core, case, _carlos, _maria, document, storage = create_case_people_document(session, tmp_path)
    core.create_person(case.id, schemas.PersonCreate(
        first_name="Carlos", last_name="Silva", roles=["other"]
    ))
    result = DocumentClassificationService(session, storage, FakeClassifier()).classify(document.id)
    assert result.suggested_person_id is None
    assert any("multiple people" in item["value"] for item in result.evidence_json)


def test_accept_correct_reject_and_multiple_attempt_history(session, tmp_path):
    _core, _case, carlos, maria, document, storage = create_case_people_document(session, tmp_path)
    service = DocumentClassificationService(session, storage, FakeClassifier())
    accepted = service.classify(document.id)
    service.accept(document.id, accepted.id, "synthetic.employee")
    reloaded = session.get(models.Document, document.id)
    assert (reloaded.document_type, reloaded.person_id) == ("bank_statements", carlos.id)
    assert accepted.reviewed_by == "synthetic.employee"

    corrected = service.classify(document.id)
    service.correct(document.id, corrected.id, schemas.ClassificationCorrection(
        reviewed_by="synthetic.employee", document_type="passport_bio_page", person_id=maria.id
    ))
    reloaded = session.get(models.Document, document.id)
    assert (reloaded.document_type, reloaded.person_id) == ("passport_bio_page", maria.id)
    assert corrected.suggested_document_type == "bank_statements"
    assert corrected.corrected_document_type == "passport_bio_page"

    rejected = service.classify(document.id)
    before = (reloaded.document_type, reloaded.person_id)
    service.reject(document.id, rejected.id, "synthetic.employee")
    session.refresh(reloaded)
    assert (reloaded.document_type, reloaded.person_id) == before
    assert [item.id for item in service.list_classifications(document.id)] == [
        rejected.id, corrected.id, accepted.id
    ]


def test_accept_preserves_manual_field_when_classifier_has_no_suggestion(session, tmp_path):
    _core, _case, carlos, _maria, document, storage = create_case_people_document(session, tmp_path)
    DocumentMatchingService(session).update_document(
        document.id,
        schemas.DocumentUpdate(document_type="identity_document", person_id=carlos.id),
    )
    classifier = FakeClassifier(ClassifierResult(
        document_type="passport_bio_page",
        owner_name=None,
        confidence=0.7,
        evidence=[ClassificationEvidenceItem("classification", "Passport marker")],
    ))
    service = DocumentClassificationService(session, storage, classifier)
    suggestion = service.classify(document.id)
    unchanged = session.get(models.Document, document.id)
    assert (unchanged.document_type, unchanged.person_id) == ("identity_document", carlos.id)
    service.accept(document.id, suggestion.id, "synthetic.employee")
    session.refresh(unchanged)
    assert (unchanged.document_type, unchanged.person_id) == ("passport_bio_page", carlos.id)


def test_accept_uses_existing_match_safety_and_does_not_auto_match_or_fulfil(session, tmp_path):
    core, case, carlos, maria, document, storage = create_case_people_document(session, tmp_path)
    DocumentMatchingService(session).update_document(
        document.id,
        schemas.DocumentUpdate(document_type="bank_statements", person_id=carlos.id),
    )
    requirement = core.create_requirement(case.id, schemas.RequirementCreate(
        document_type="bank_statements", owner_role="sponsor", owner_person_id=carlos.id,
        requirement_level="required", reason="Synthetic requirement"
    ))
    matching = DocumentMatchingService(session)
    matching.create_match(requirement.id, document.id, schemas.RequirementDocumentMatchCreate())
    classifier = FakeClassifier(ClassifierResult(
        document_type="passport_bio_page", owner_name="Maria Silva", confidence=0.9,
        evidence=[ClassificationEvidenceItem("classification", "Passport marker")],
    ))
    service = DocumentClassificationService(session, storage, classifier)
    suggestion = service.classify(document.id)
    with pytest.raises(DomainValidationError, match="remove incompatible"):
        service.accept(document.id, suggestion.id, "synthetic.employee")
    session.rollback()
    assert requirement.fulfillment_status == models.RequirementFulfillmentStatus.PENDING
    assert len(matching.list_document_matches(document.id)) == 1


def test_image_path_reaches_provider_without_ocr_or_quality_output(session, tmp_path):
    jpeg = b"\xff\xd8\xffsynthetic-image-content"
    _core, _case, _carlos, _maria, document, storage = create_case_people_document(
        session, tmp_path, content=jpeg, mime_type="image/jpeg"
    )
    classifier = FakeClassifier(ClassifierResult(
        document_type="digital_photo", owner_name=None, confidence=0.8,
        evidence=[ClassificationEvidenceItem("classification", "Synthetic image fixture")],
    ))
    result = DocumentClassificationService(session, storage, classifier).classify(document.id)
    assert classifier.received[0].mime_type == "image/jpeg"
    assert classifier.received[0].text == ""
    assert classifier.received[0].binary_content == jpeg
    assert "quality" not in result.raw_result_json
    assert session.get(models.Document, document.id).quality_status == "not_checked"


def test_provider_failure_is_persisted_and_manual_workflow_remains_available(session, tmp_path):
    _core, _case, carlos, _maria, document, storage = create_case_people_document(session, tmp_path)
    service = DocumentClassificationService(
        session, storage, FakeClassifier(error=RuntimeError("private provider detail"))
    )
    failed = service.classify(document.id)
    assert failed.status == models.ClassificationReviewStatus.FAILED
    assert failed.failure_reason == "Classification provider returned an invalid result or failed."
    assert "private" not in failed.failure_reason
    updated = DocumentMatchingService(session).update_document(
        document.id,
        schemas.DocumentUpdate(document_type="bank_statements", person_id=carlos.id),
    )
    assert updated.document_type == "bank_statements"


def test_missing_provider_is_safe_and_explicit(monkeypatch, session, tmp_path):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    assert isinstance(classifier_from_environment(), UnavailableDocumentClassifier)
    _core, _case, _carlos, _maria, document, storage = create_case_people_document(session, tmp_path)
    failed = DocumentClassificationService(
        session, storage, classifier_from_environment()
    ).classify(document.id)
    assert failed.status == models.ClassificationReviewStatus.FAILED
    assert "not configured" in failed.failure_reason


def test_unreviewed_suggestion_does_not_resolve_next_action(session, tmp_path):
    core, case, _carlos, _maria, document, storage = create_case_people_document(session, tmp_path)
    for key in ("sponsor.exists", "host.exists"):
        core.create_fact(case.id, schemas.FactCreate(
            key=key,
            value_json=False,
            source_type="manual",
            source_reference="Synthetic test",
            status="confirmed",
        ))
    suggestion = DocumentClassificationService(
        session, storage, FakeClassifier()
    ).classify(document.id)
    assert suggestion.status == models.ClassificationReviewStatus.SUGGESTED
    action = WorkflowService(session).get_next_action(case.id)
    assert action.type == "ASSIGN_DOCUMENT"
    assert action.document_id == document.id


def test_classification_api_lifecycle(session, tmp_path):
    storage = LocalStorageProvider(tmp_path / "api-classification-storage")
    classifier = FakeClassifier()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[storage_provider] = lambda: storage
    app.dependency_overrides[classification_provider] = lambda: classifier
    client = TestClient(app)
    try:
        case = client.post("/cases", json={
            "case_number": "M6-API", "visa_type": "TRV", "purpose": "Synthetic"
        }).json()
        person = client.post(f"/cases/{case['id']}/persons", json={
            "first_name": "Carlos", "last_name": "Silva", "roles": ["sponsor"]
        }).json()
        upload = client.post(
            f"/cases/{case['id']}/documents/upload",
            files={"file": ("synthetic.pdf", synthetic_pdf("Synthetic statement"), "application/pdf")},
        )
        document = upload.json()
        suggestion = client.post(f"/documents/{document['id']}/classify")
        assert suggestion.status_code == 201
        assert suggestion.json()["status"] == "suggested"
        assert suggestion.json()["suggested_person_id"] == person["id"]
        history = client.get(f"/documents/{document['id']}/classifications")
        assert history.status_code == 200
        assert len(history.json()) == 1
        accepted = client.post(
            f"/documents/{document['id']}/classifications/{suggestion.json()['id']}/accept",
            json={"reviewed_by": "synthetic.employee"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "accepted"
        assert client.get(f"/documents/{document['id']}").json()["person_id"] == person["id"]
    finally:
        app.dependency_overrides.clear()


def test_reject_and_correct_api_endpoints(session, tmp_path):
    storage = LocalStorageProvider(tmp_path / "api-review-storage")
    classifier = FakeClassifier()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[storage_provider] = lambda: storage
    app.dependency_overrides[classification_provider] = lambda: classifier
    client = TestClient(app)
    try:
        case = client.post("/cases", json={
            "case_number": "M6-API-REVIEW", "visa_type": "TRV", "purpose": "Synthetic"
        }).json()
        carlos = client.post(f"/cases/{case['id']}/persons", json={
            "first_name": "Carlos", "last_name": "Silva", "roles": ["sponsor"]
        }).json()
        document = client.post(
            f"/cases/{case['id']}/documents/upload",
            files={"file": ("synthetic.pdf", synthetic_pdf("Synthetic"), "application/pdf")},
        ).json()
        first = client.post(f"/documents/{document['id']}/classify").json()
        rejected = client.post(
            f"/documents/{document['id']}/classifications/{first['id']}/reject",
            json={"reviewed_by": "synthetic.employee"},
        )
        assert rejected.json()["status"] == "rejected"
        assert client.get(f"/documents/{document['id']}").json()["document_type"] is None

        second = client.post(f"/documents/{document['id']}/classify").json()
        corrected = client.post(
            f"/documents/{document['id']}/classifications/{second['id']}/correct",
            json={
                "reviewed_by": "synthetic.employee",
                "document_type": "identity_document",
                "person_id": carlos["id"],
            },
        )
        assert corrected.json()["status"] == "corrected"
        assert corrected.json()["suggested_document_type"] == "bank_statements"
        assert corrected.json()["corrected_document_type"] == "identity_document"
    finally:
        app.dependency_overrides.clear()
