from __future__ import annotations

import uuid
import os
from pathlib import PurePath
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session

from ..classifiers import DocumentClassifier, classifier_from_environment
from ..fact_extractors import FactExtractor, fact_extractor_from_environment
from .. import models
from ..quality_evaluators import (
    TypeSpecificQualityEvaluator,
    quality_evaluator_from_environment,
)
from ..database import get_session
from ..authorization import CurrentUser, enforce_workflow_target
from ..schemas import core as schemas
from ..schemas.auth import AuditEventRead
from ..services import (
    CaseApplicationService,
    CoreDataService,
    ConversationFactExtractionService,
    ConversationImportService,
    DocumentClassificationService,
    DocumentMatchingService,
    DocumentQualityService,
    DocumentUploadService,
    DocumentUploadTooLarge,
    RequirementEngine,
    RequirementCompletenessService,
    WorkflowService,
    UnsupportedDocumentFile,
)
from ..services.requirements import DEFAULT_RULE_CATALOG
from ..storage import LocalStorageProvider, StorageProvider
from ..services.audit import case_audit_events


router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


def storage_provider() -> StorageProvider:
    return LocalStorageProvider.from_environment()


StorageDep = Annotated[StorageProvider, Depends(storage_provider)]


def generated_storage_provider() -> StorageProvider:
    return LocalStorageProvider.generated_from_environment()


GeneratedStorageDep = Annotated[StorageProvider, Depends(generated_storage_provider)]


def classification_provider() -> DocumentClassifier:
    return classifier_from_environment()


ClassifierDep = Annotated[DocumentClassifier, Depends(classification_provider)]


def quality_provider() -> TypeSpecificQualityEvaluator:
    return quality_evaluator_from_environment()


QualityProviderDep = Annotated[TypeSpecificQualityEvaluator, Depends(quality_provider)]


def fact_extraction_provider() -> FactExtractor:
    return fact_extractor_from_environment()


FactExtractorDep = Annotated[FactExtractor, Depends(fact_extraction_provider)]


def configured_max_conversation_bytes() -> int:
    raw = os.environ.get("MAX_CONVERSATION_IMPORT_MB", "2")
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError("MAX_CONVERSATION_IMPORT_MB must be an integer") from error
    if value < 1 or value > 20:
        raise RuntimeError("MAX_CONVERSATION_IMPORT_MB must be between 1 and 20")
    return value * 1024 * 1024


def service(session: Session) -> CoreDataService:
    return CoreDataService(session)


@router.post("/cases", response_model=schemas.CaseRead, status_code=status.HTTP_201_CREATED)
def create_case(payload: schemas.CaseCreate, session: SessionDep, user: CurrentUser):
    return CaseApplicationService(session).create_case(payload, audit_actor=user)


@router.get("/cases", response_model=list[schemas.CaseRead])
def list_cases(session: SessionDep):
    return service(session).list_cases()


@router.get("/cases/{case_id}", response_model=schemas.CaseRead)
def get_case(case_id: uuid.UUID, session: SessionDep):
    return service(session).get_case(case_id)


@router.patch("/cases/{case_id}", response_model=schemas.CaseRead)
def update_case(case_id: uuid.UUID, payload: schemas.CaseUpdate, session: SessionDep):
    return CaseApplicationService(session).update_case(case_id, payload)


@router.post("/cases/{case_id}/persons", response_model=schemas.PersonRead, status_code=status.HTTP_201_CREATED)
def create_person(case_id: uuid.UUID, payload: schemas.PersonCreate, session: SessionDep):
    return CaseApplicationService(session).create_person(case_id, payload)


@router.get("/cases/{case_id}/persons", response_model=list[schemas.PersonRead])
def list_persons(case_id: uuid.UUID, session: SessionDep):
    return service(session).list_persons(case_id)


@router.get("/persons/{person_id}", response_model=schemas.PersonRead)
def get_person(person_id: uuid.UUID, session: SessionDep):
    return service(session).get_person(person_id)


@router.patch("/persons/{person_id}", response_model=schemas.PersonRead)
def update_person(person_id: uuid.UUID, payload: schemas.PersonUpdate, session: SessionDep):
    return CaseApplicationService(session).update_person(person_id, payload)


@router.post("/cases/{case_id}/facts", response_model=schemas.FactRead, status_code=status.HTTP_201_CREATED)
def create_fact(case_id: uuid.UUID, payload: schemas.FactCreate, session: SessionDep):
    return CaseApplicationService(session).create_fact(case_id, payload)


@router.get("/cases/{case_id}/facts", response_model=list[schemas.FactRead])
def list_facts(case_id: uuid.UUID, session: SessionDep):
    return service(session).list_facts(case_id)


@router.get("/facts/{fact_id}", response_model=schemas.FactRead)
def get_fact(fact_id: uuid.UUID, session: SessionDep):
    return service(session).get_fact(fact_id)


@router.patch("/facts/{fact_id}", response_model=schemas.FactRead)
def update_fact(fact_id: uuid.UUID, payload: schemas.FactUpdate, session: SessionDep):
    return CaseApplicationService(session).update_fact(fact_id, payload)


@router.post(
    "/cases/{case_id}/conversations/whatsapp/paste",
    response_model=schemas.ConversationImportRead,
    status_code=status.HTTP_201_CREATED,
)
def paste_whatsapp_conversation(
    case_id: uuid.UUID, payload: schemas.ConversationPasteCreate, session: SessionDep
):
    if len(payload.text.encode("utf-8")) > configured_max_conversation_bytes():
        raise DocumentUploadTooLarge("conversation exceeds maximum import size")
    return ConversationImportService(session).import_text(
        case_id,
        payload.text,
        source_type=models.ConversationSourceType.WHATSAPP_PASTE,
        imported_by=payload.imported_by,
    )


@router.post(
    "/cases/{case_id}/conversations/whatsapp/upload",
    response_model=schemas.ConversationImportRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_whatsapp_conversation(
    case_id: uuid.UUID,
    session: SessionDep,
    file: UploadFile = File(...),
    imported_by: str | None = Form(default=None),
):
    filename = PurePath(file.filename or "conversation.txt").name
    if not filename.casefold().endswith(".txt") or file.content_type not in {
        "text/plain", "application/octet-stream"
    }:
        raise UnsupportedDocumentFile("only plain-text .txt conversation exports are supported")
    try:
        binary = file.file.read(configured_max_conversation_bytes() + 1)
    finally:
        file.file.close()
    if len(binary) > configured_max_conversation_bytes():
        raise DocumentUploadTooLarge("conversation exceeds maximum import size")
    if b"\x00" in binary and not binary.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise UnsupportedDocumentFile("conversation export appears to be binary")
    try:
        if binary.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = binary.decode("utf-16")
        else:
            text = binary.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise UnsupportedDocumentFile("conversation export must be UTF-8 or BOM-marked UTF-16 text") from error
    return ConversationImportService(session).import_text(
        case_id,
        text,
        source_type=models.ConversationSourceType.WHATSAPP_EXPORT,
        imported_by=imported_by,
        original_filename=filename,
    )


@router.get(
    "/cases/{case_id}/conversations",
    response_model=list[schemas.ConversationImportRead],
)
def list_conversations(case_id: uuid.UUID, session: SessionDep):
    return ConversationImportService(session).list_case(case_id)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[schemas.ConversationMessageRead],
)
def list_conversation_messages(conversation_id: uuid.UUID, session: SessionDep):
    return ConversationImportService(session).list_messages(conversation_id)


@router.post(
    "/conversations/{conversation_id}/extract-facts",
    response_model=schemas.FactExtractionRunRead,
    status_code=status.HTTP_201_CREATED,
)
def extract_conversation_facts(
    conversation_id: uuid.UUID, session: SessionDep, extractor: FactExtractorDep
):
    return ConversationFactExtractionService(session, extractor).extract(conversation_id)


@router.get(
    "/conversations/{conversation_id}/extraction-runs",
    response_model=list[schemas.FactExtractionRunRead],
)
def list_fact_extraction_runs(conversation_id: uuid.UUID, session: SessionDep, extractor: FactExtractorDep):
    return ConversationFactExtractionService(session, extractor).list_runs(conversation_id)


@router.get(
    "/conversations/{conversation_id}/fact-candidates",
    response_model=list[schemas.FactExtractionCandidateRead],
)
def list_fact_candidates(conversation_id: uuid.UUID, session: SessionDep, extractor: FactExtractorDep):
    return ConversationFactExtractionService(session, extractor).list_candidates(conversation_id)


@router.post(
    "/fact-candidates/{candidate_id}/accept",
    response_model=schemas.FactExtractionCandidateRead,
)
def accept_fact_candidate(candidate_id: uuid.UUID, payload: schemas.FactCandidateReview, session: SessionDep, extractor: FactExtractorDep):
    return ConversationFactExtractionService(session, extractor).accept(candidate_id, payload)


@router.post(
    "/fact-candidates/{candidate_id}/correct",
    response_model=schemas.FactExtractionCandidateRead,
)
def correct_fact_candidate(candidate_id: uuid.UUID, payload: schemas.FactCandidateCorrection, session: SessionDep, extractor: FactExtractorDep):
    return ConversationFactExtractionService(session, extractor).correct(candidate_id, payload)


@router.post(
    "/fact-candidates/{candidate_id}/reject",
    response_model=schemas.FactExtractionCandidateRead,
)
def reject_fact_candidate(candidate_id: uuid.UUID, payload: schemas.FactCandidateReview, session: SessionDep, extractor: FactExtractorDep):
    return ConversationFactExtractionService(session, extractor).reject(candidate_id, payload)


@router.post("/cases/{case_id}/requirements", response_model=schemas.RequirementRead, status_code=status.HTTP_201_CREATED)
def create_requirement(case_id: uuid.UUID, payload: schemas.RequirementCreate, session: SessionDep):
    return service(session).create_requirement(case_id, payload)


@router.get("/cases/{case_id}/requirements", response_model=list[schemas.RequirementRead])
def list_requirements(case_id: uuid.UUID, session: SessionDep):
    return service(session).list_requirements(case_id)


@router.post(
    "/cases/{case_id}/requirements/evaluate",
    response_model=schemas.RequirementEvaluationRead,
)
def evaluate_requirements(case_id: uuid.UUID, session: SessionDep):
    return RequirementEngine(session).evaluate(case_id)


@router.get("/requirements/{requirement_id}", response_model=schemas.RequirementRead)
def get_requirement(requirement_id: uuid.UUID, session: SessionDep):
    return service(session).get_requirement(requirement_id)


@router.patch("/requirements/{requirement_id}", response_model=schemas.RequirementRead)
def update_requirement(requirement_id: uuid.UUID, payload: schemas.RequirementUpdate, session: SessionDep):
    return service(session).update_requirement(requirement_id, payload)


@router.post("/cases/{case_id}/documents", response_model=schemas.DocumentRead, status_code=status.HTTP_201_CREATED)
def create_document(case_id: uuid.UUID, payload: schemas.DocumentCreate, session: SessionDep):
    return service(session).create_document(case_id, payload)


@router.post(
    "/cases/{case_id}/documents/upload",
    response_model=schemas.DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    case_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    file: UploadFile = File(...),
    document_type: str | None = Form(default=None),
    person_id: uuid.UUID | None = Form(default=None),
):
    try:
        return DocumentUploadService(session, storage).upload(
            case_id,
            file.file,
            original_filename=file.filename,
            declared_mime_type=file.content_type,
            document_type=document_type or None,
            person_id=person_id,
        )
    finally:
        file.file.close()


@router.get("/cases/{case_id}/documents", response_model=list[schemas.DocumentRead])
def list_documents(case_id: uuid.UUID, session: SessionDep):
    return service(session).list_documents(case_id)


@router.get("/document-types", response_model=list[schemas.DocumentTypeRead])
def list_document_types():
    return list(DEFAULT_RULE_CATALOG.document_types.values())


@router.get(
    "/cases/{case_id}/document-matches",
    response_model=list[schemas.RequirementDocumentMatchRead],
)
def list_case_document_matches(case_id: uuid.UUID, session: SessionDep):
    return DocumentMatchingService(session).list_case_matches(case_id)


@router.get(
    "/documents/{document_id}/matching-requirements",
    response_model=list[schemas.RequirementRead],
)
def matching_requirements(document_id: uuid.UUID, session: SessionDep):
    return DocumentMatchingService(session).compatible_requirements(document_id)


@router.get(
    "/documents/{document_id}/requirements",
    response_model=list[schemas.MatchedRequirementRead],
)
def list_matched_requirements(document_id: uuid.UUID, session: SessionDep):
    matching = DocumentMatchingService(session)
    return [
        {"match": match, "requirement": match.requirement}
        for match in matching.list_document_matches(document_id)
    ]


@router.get(
    "/requirements/{requirement_id}/documents",
    response_model=list[schemas.MatchedDocumentRead],
)
def list_matched_documents(requirement_id: uuid.UUID, session: SessionDep):
    matching = DocumentMatchingService(session)
    return [
        {"match": match, "document": match.document}
        for match in matching.list_requirement_matches(requirement_id)
    ]


@router.post(
    "/requirements/{requirement_id}/documents/{document_id}",
    response_model=schemas.RequirementDocumentMatchRead,
    status_code=status.HTTP_201_CREATED,
)
def match_document(
    requirement_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: schemas.RequirementDocumentMatchCreate,
    session: SessionDep,
):
    return DocumentMatchingService(session).create_match(
        requirement_id, document_id, payload
    )


@router.delete(
    "/requirements/{requirement_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unmatch_document(
    requirement_id: uuid.UUID, document_id: uuid.UUID, session: SessionDep
):
    DocumentMatchingService(session).remove_match(requirement_id, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/documents/{document_id}/content")
def get_document_content(
    document_id: uuid.UUID, session: SessionDep, storage: StorageDep
):
    document = service(session).get_document(document_id)
    stream = storage.open(document.storage_path)
    disposition = f"inline; filename*=UTF-8''{quote(document.original_filename)}"
    return StreamingResponse(
        stream,
        media_type=document.mime_type,
        headers={"Content-Disposition": disposition},
        background=BackgroundTask(stream.close),
    )


@router.post(
    "/documents/{document_id}/classify",
    response_model=schemas.DocumentClassificationRead,
    status_code=status.HTTP_201_CREATED,
)
def classify_document(
    document_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    classifier: ClassifierDep,
):
    return DocumentClassificationService(session, storage, classifier).classify(document_id)


@router.get(
    "/documents/{document_id}/classifications",
    response_model=list[schemas.DocumentClassificationRead],
)
def list_document_classifications(
    document_id: uuid.UUID, session: SessionDep, storage: StorageDep, classifier: ClassifierDep
):
    return DocumentClassificationService(
        session, storage, classifier
    ).list_classifications(document_id)


@router.post(
    "/documents/{document_id}/classifications/{classification_id}/accept",
    response_model=schemas.DocumentClassificationRead,
)
def accept_document_classification(
    document_id: uuid.UUID,
    classification_id: uuid.UUID,
    payload: schemas.ClassificationReview,
    session: SessionDep,
    storage: StorageDep,
    classifier: ClassifierDep,
):
    return DocumentClassificationService(session, storage, classifier).accept(
        document_id, classification_id, payload.reviewed_by
    )


@router.post(
    "/documents/{document_id}/classifications/{classification_id}/correct",
    response_model=schemas.DocumentClassificationRead,
)
def correct_document_classification(
    document_id: uuid.UUID,
    classification_id: uuid.UUID,
    payload: schemas.ClassificationCorrection,
    session: SessionDep,
    storage: StorageDep,
    classifier: ClassifierDep,
):
    return DocumentClassificationService(session, storage, classifier).correct(
        document_id, classification_id, payload
    )


@router.post(
    "/documents/{document_id}/classifications/{classification_id}/reject",
    response_model=schemas.DocumentClassificationRead,
)
def reject_document_classification(
    document_id: uuid.UUID,
    classification_id: uuid.UUID,
    payload: schemas.ClassificationReview,
    session: SessionDep,
    storage: StorageDep,
    classifier: ClassifierDep,
):
    return DocumentClassificationService(session, storage, classifier).reject(
        document_id, classification_id, payload.reviewed_by
    )


@router.get("/documents/{document_id}", response_model=schemas.DocumentRead)
def get_document(document_id: uuid.UUID, session: SessionDep):
    return service(session).get_document(document_id)


@router.post(
    "/documents/{document_id}/quality-check",
    response_model=schemas.DocumentQualityCheckRead,
    status_code=status.HTTP_201_CREATED,
)
def run_document_quality_check(
    document_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    evaluator: QualityProviderDep,
):
    return DocumentQualityService(session, storage, evaluator).run(document_id)


@router.get(
    "/documents/{document_id}/quality-checks",
    response_model=list[schemas.DocumentQualityCheckRead],
)
def list_document_quality_checks(
    document_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    evaluator: QualityProviderDep,
):
    return DocumentQualityService(session, storage, evaluator).list_checks(document_id)


@router.post(
    "/documents/{document_id}/quality-checks/{check_id}/accept",
    response_model=schemas.DocumentQualityCheckRead,
)
def accept_document_quality(
    document_id: uuid.UUID,
    check_id: uuid.UUID,
    payload: schemas.QualityManualReview,
    session: SessionDep,
    storage: StorageDep,
    evaluator: QualityProviderDep,
):
    return DocumentQualityService(session, storage, evaluator).accept(
        document_id, check_id, payload
    )


@router.post(
    "/documents/{document_id}/quality-checks/{check_id}/reject",
    response_model=schemas.DocumentQualityCheckRead,
)
def reject_document_quality(
    document_id: uuid.UUID,
    check_id: uuid.UUID,
    payload: schemas.QualityManualReview,
    session: SessionDep,
    storage: StorageDep,
    evaluator: QualityProviderDep,
):
    return DocumentQualityService(session, storage, evaluator).reject(
        document_id, check_id, payload
    )


@router.post(
    "/requirements/{requirement_id}/evaluate-completeness",
    response_model=schemas.RequirementCompletenessRead,
)
def evaluate_requirement_completeness(
    requirement_id: uuid.UUID, session: SessionDep
):
    return RequirementCompletenessService(session).evaluate(
        requirement_id, trigger="explicit"
    )


@router.get(
    "/requirements/{requirement_id}/completeness-evaluations",
    response_model=list[schemas.RequirementCompletenessRead],
)
def list_requirement_completeness(
    requirement_id: uuid.UUID, session: SessionDep
):
    return RequirementCompletenessService(session).list_evaluations(requirement_id)


@router.get(
    "/requirements/{requirement_id}/fulfillment-events",
    response_model=list[schemas.RequirementFulfillmentEventRead],
)
def list_requirement_fulfillment_events(
    requirement_id: uuid.UUID, session: SessionDep
):
    return RequirementCompletenessService(session).list_fulfillment_events(
        requirement_id
    )


@router.patch("/documents/{document_id}", response_model=schemas.DocumentRead)
def update_document(document_id: uuid.UUID, payload: schemas.DocumentUpdate, session: SessionDep):
    return DocumentMatchingService(session).update_document(document_id, payload)


@router.post("/cases/{case_id}/tasks", response_model=schemas.TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(case_id: uuid.UUID, payload: schemas.TaskCreate, session: SessionDep):
    return service(session).create_task(case_id, payload)


@router.get("/cases/{case_id}/tasks", response_model=list[schemas.TaskRead])
def list_tasks(case_id: uuid.UUID, session: SessionDep):
    return service(session).list_tasks(case_id)


@router.get("/tasks/{task_id}", response_model=schemas.TaskRead)
def get_task(task_id: uuid.UUID, session: SessionDep):
    return service(session).get_task(task_id)


@router.patch("/tasks/{task_id}", response_model=schemas.TaskRead)
def update_task(task_id: uuid.UUID, payload: schemas.TaskUpdate, session: SessionDep):
    return service(session).update_task(task_id, payload)


@router.get("/cases/{case_id}/workflow", response_model=schemas.WorkflowRead)
def get_workflow(case_id: uuid.UUID, session: SessionDep, storage: GeneratedStorageDep):
    workflow = WorkflowService(session, storage)
    return {
        "case_id": case_id,
        "current_state": workflow.get_state(case_id),
        "allowed_targets": workflow.allowed_targets(case_id),
        "history": workflow.history(case_id),
    }


@router.get("/cases/{case_id}/next-action", response_model=schemas.NextActionRead)
def get_next_action(case_id: uuid.UUID, session: SessionDep, storage: GeneratedStorageDep):
    return WorkflowService(session, storage).get_next_action(case_id).as_dict()


@router.post(
    "/cases/{case_id}/transition",
    response_model=schemas.WorkflowTransitionResult,
)
def transition_case(
    case_id: uuid.UUID,
    payload: schemas.WorkflowTransitionRequest,
    session: SessionDep,
    storage: GeneratedStorageDep,
    user: CurrentUser,
):
    workflow = WorkflowService(session, storage)
    enforce_workflow_target(
        user, payload.target_state.value, current_state=workflow.get_state(case_id).value
    )
    previous, case, transition = workflow.transition(
        case_id,
        payload.target_state,
        actor=payload.actor,
        reason=payload.reason,
        audit_actor=user,
    )
    return {
        "case_id": case.id,
        "previous_state": previous,
        "current_state": case.workflow_state,
        "transition": transition,
    }


@router.get("/cases/{case_id}/audit-events", response_model=list[AuditEventRead])
def list_case_audit_events(case_id: uuid.UUID, session: SessionDep):
    service(session).get_case(case_id)
    events = case_audit_events(session, case_id)
    users = {
        event.actor_user_id: session.get(models.User, event.actor_user_id)
        for event in events if event.actor_user_id is not None
    }
    return [AuditEventRead.model_validate(event).model_copy(update={
        "actor_display_name": users[event.actor_user_id].display_name if users.get(event.actor_user_id) else None,
        "actor_email": users[event.actor_user_id].email if users.get(event.actor_user_id) else None,
    }) for event in events]
