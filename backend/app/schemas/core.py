from __future__ import annotations

import uuid
from datetime import datetime
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models import (
    ClassificationReviewStatus,
    CompletenessStatus,
    ConversationParseStatus,
    ConversationSourceType,
    DocumentClassificationState,
    DocumentQualityState,
    FactCandidateStatus,
    FactExtractionRunStatus,
    QualityCheckStatus,
    QualityReviewDecision,
    RequirementFulfillmentSource,
    RequirementFulfillmentStatus,
    WorkflowState,
    OperationalRole,
)


PersonRole = OperationalRole
RequirementOwnerRole = Literal["applicant", "sponsor", "host", "representative", "spouse", "child", "other"]
FactSource = Literal["google_form", "whatsapp", "document", "manual", "derived"]
FactStatus = Literal["confirmed", "proposed", "conflict", "rejected"]
RequirementLevel = Literal["required", "conditional", "supporting", "optional"]
TaskStatus = Literal["open", "in_progress", "completed", "cancelled"]


def validate_completeness_policy(value: dict[str, Any]) -> dict[str, Any]:
    mode = value.get("mode")
    if mode == "single_document" and set(value) == {"mode"}:
        return value
    if mode == "month_coverage" and set(value) == {"mode", "required_months"}:
        months = value.get("required_months")
        if (
            isinstance(months, list)
            and months
            and all(isinstance(month, str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month) for month in months)
            and len(months) == len(set(months))
        ):
            return value
    raise ValueError("completeness policy must be single_document or unique required YYYY-MM months")


class ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_number: str | None = Field(default=None, min_length=1, max_length=64)
    visa_type: str = Field(default="canada_trv", min_length=1, max_length=64)
    purpose: str = Field(default="To be confirmed", min_length=1, max_length=128)


class CaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_number: str | None = Field(default=None, min_length=1, max_length=64)
    visa_type: str | None = Field(default=None, min_length=1, max_length=64)
    purpose: str | None = Field(default=None, min_length=1, max_length=128)


class CaseRead(ReadModel):
    id: uuid.UUID
    case_number: str
    visa_type: str
    purpose: str
    workflow_state: WorkflowState
    created_at: datetime
    updated_at: datetime


class PersonCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=128)
    last_name: str = Field(min_length=1, max_length=128)
    roles: list[PersonRole] = Field(min_length=1)

    @field_validator("roles")
    @classmethod
    def roles_are_unique(cls, value: list[PersonRole]) -> list[PersonRole]:
        if len(value) != len(set(value)):
            raise ValueError("roles must not contain duplicates")
        return value


class PersonUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=128)
    last_name: str | None = Field(default=None, min_length=1, max_length=128)
    roles: list[PersonRole] | None = Field(default=None, min_length=1)

    @field_validator("roles")
    @classmethod
    def roles_are_unique(cls, value: list[PersonRole] | None) -> list[PersonRole] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("roles must not contain duplicates")
        return value


class PersonRead(PersonCreate, ReadModel):
    id: uuid.UUID
    case_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class FactCreate(BaseModel):
    person_id: uuid.UUID | None = None
    key: str = Field(min_length=1, max_length=255)
    value_json: Any
    source_type: FactSource
    source_reference: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: FactStatus


class FactUpdate(BaseModel):
    person_id: uuid.UUID | None = None
    key: str | None = Field(default=None, min_length=1, max_length=255)
    value_json: Any | None = None
    source_type: FactSource | None = None
    source_reference: str | None = Field(default=None, min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: FactStatus | None = None


class FactRead(FactCreate, ReadModel):
    id: uuid.UUID
    case_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ConversationPasteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2_000_000)
    imported_by: str | None = Field(default=None, min_length=1, max_length=255)


class ConversationImportRead(ReadModel):
    id: uuid.UUID
    case_id: uuid.UUID
    source_type: ConversationSourceType
    original_filename: str | None
    imported_by: str | None
    content_hash: str
    parse_status: ConversationParseStatus
    parse_warnings_json: list[dict[str, Any]]
    message_count: int
    imported_at: datetime


class ConversationMessageRead(ReadModel):
    id: uuid.UUID
    conversation_import_id: uuid.UUID
    case_id: uuid.UUID
    sequence_number: int
    sender: str | None
    message_timestamp: datetime | None
    text: str
    source_reference: str
    created_at: datetime


class FactExtractionRunRead(ReadModel):
    id: uuid.UUID
    conversation_import_id: uuid.UUID
    status: FactExtractionRunStatus
    provider: str
    model_version: str | None
    candidate_count: int
    rejected_output_count: int
    failure_reason: str | None
    created_at: datetime
    completed_at: datetime | None


class FactExtractionCandidateRead(ReadModel):
    id: uuid.UUID
    case_id: uuid.UUID
    conversation_import_id: uuid.UUID | None
    extraction_run_id: uuid.UUID | None
    key: str
    value_json: Any
    confidence: float
    evidence: str
    source_message_ids_json: list[str]
    provider: str
    model_version: str | None
    status: FactCandidateStatus
    conflicting_fact_id: uuid.UUID | None
    authoritative_fact_id: uuid.UUID | None
    corrected_value_json: Any | None
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: str | None
    review_reason: str | None


class FactCandidateReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_by: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=3, max_length=2000)


class FactCandidateCorrection(FactCandidateReview):
    value_json: Any


class RequirementCreate(BaseModel):
    document_type: str = Field(min_length=1, max_length=128)
    owner_role: RequirementOwnerRole
    owner_person_id: uuid.UUID | None = None
    requirement_level: RequirementLevel
    rule_id: str | None = Field(default=None, max_length=128)
    reason: str = Field(min_length=1)
    is_blocking: bool = True
    active: bool = True
    completeness_policy_json: dict[str, Any] = Field(
        default_factory=lambda: {"mode": "single_document"}
    )

    _validate_completeness_policy = field_validator("completeness_policy_json")(
        validate_completeness_policy
    )


class RequirementUpdate(BaseModel):
    document_type: str | None = Field(default=None, min_length=1, max_length=128)
    owner_role: RequirementOwnerRole | None = None
    owner_person_id: uuid.UUID | None = None
    requirement_level: RequirementLevel | None = None
    rule_id: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default=None, min_length=1)
    is_blocking: bool | None = None
    active: bool | None = None
    fulfillment_status: RequirementFulfillmentStatus | None = None
    waiver_reason: str | None = Field(default=None, min_length=1)
    waived_by: str | None = Field(default=None, min_length=1, max_length=255)
    completeness_policy_json: dict[str, Any] | None = None

    _validate_completeness_policy = field_validator("completeness_policy_json")(
        lambda value: validate_completeness_policy(value) if value is not None else value
    )


class RequirementRead(RequirementCreate, ReadModel):
    id: uuid.UUID
    case_id: uuid.UUID
    fulfillment_status: RequirementFulfillmentStatus
    waiver_reason: str | None
    waived_by: str | None
    waived_at: datetime | None
    fulfillment_source: RequirementFulfillmentSource | None
    fulfillment_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RequirementEvaluationRead(BaseModel):
    created: list[RequirementRead]
    reactivated: list[RequirementRead]
    deactivated: list[RequirementRead]
    unchanged: list[RequirementRead]


class DocumentCreate(BaseModel):
    person_id: uuid.UUID | None = None
    document_type: str | None = Field(default=None, max_length=128)
    original_filename: str = Field(min_length=1, max_length=512)
    storage_path: str = Field(min_length=1)
    mime_type: str = Field(min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=32)
    classification_status: DocumentClassificationState = DocumentClassificationState.UNCLASSIFIED
    quality_status: DocumentQualityState = DocumentQualityState.NOT_CHECKED
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class DocumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: uuid.UUID | None = None
    document_type: str | None = Field(default=None, max_length=128)


class DocumentRead(ReadModel):
    id: uuid.UUID
    case_id: uuid.UUID
    person_id: uuid.UUID | None
    document_type: str | None
    original_filename: str
    mime_type: str
    source_type: str
    classification_status: DocumentClassificationState
    quality_status: DocumentQualityState
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DocumentTypeRead(BaseModel):
    id: str
    label: str


class ClassificationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=500)


class DocumentClassificationRead(ReadModel):
    id: uuid.UUID
    document_id: uuid.UUID
    suggested_document_type: str | None
    suggested_person_id: uuid.UUID | None
    extracted_owner_name: str | None
    confidence: float | None
    evidence_json: list[ClassificationEvidence]
    provider: str
    model_version: str | None
    document_hash: str | None
    raw_result_json: dict[str, Any] | None
    status: ClassificationReviewStatus
    failure_reason: str | None
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: str | None
    corrected_document_type: str | None
    corrected_person_id: uuid.UUID | None


class ClassificationReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_by: str = Field(min_length=1, max_length=255)


class ClassificationCorrection(ClassificationReview):
    document_type: str = Field(min_length=1, max_length=128)
    person_id: uuid.UUID


class QualityCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(min_length=1, max_length=128)
    status: Literal["pass", "fail", "unknown", "manual_review", "not_applicable"]
    evidence: str | None = Field(default=None, max_length=500)
    issue: str | None = Field(default=None, max_length=500)
    evaluator: str = Field(min_length=1, max_length=64)
    confidence: float | None = Field(default=None, ge=0, le=1)


class QualityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=500)


class DocumentQualityCheckRead(ReadModel):
    id: uuid.UUID
    document_id: uuid.UUID
    status: QualityCheckStatus
    checks_json: list[QualityCheckResult]
    issues_json: list[QualityIssue]
    extracted_metadata_json: dict[str, Any]
    provider: str
    evaluator_version: str | None
    document_hash: str | None
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: str | None
    review_decision: QualityReviewDecision | None
    review_reason: str | None


class QualityManualReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_by: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=3, max_length=2000)


class RequirementCompletenessRead(ReadModel):
    id: uuid.UUID
    requirement_id: uuid.UUID
    status: CompletenessStatus
    matched_document_ids_json: list[str]
    accepted_document_ids_json: list[str]
    matched_count: int
    accepted_count: int
    coverage_json: dict[str, Any]
    missing_json: list[str]
    explanation: str
    trigger: str
    created_at: datetime


class RequirementFulfillmentEventRead(ReadModel):
    id: uuid.UUID
    requirement_id: uuid.UUID
    from_status: str
    to_status: str
    source: RequirementFulfillmentSource
    reason: str
    actor: str | None
    document_ids_json: list[str]
    created_at: datetime


class RequirementDocumentMatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: str | None = Field(default=None, min_length=1, max_length=255)
    note: str | None = Field(default=None, min_length=1)


class RequirementDocumentMatchRead(ReadModel):
    id: uuid.UUID
    requirement_id: uuid.UUID
    document_id: uuid.UUID
    created_by: str | None
    note: str | None
    created_at: datetime


class MatchedDocumentRead(BaseModel):
    match: RequirementDocumentMatchRead
    document: DocumentRead


class MatchedRequirementRead(BaseModel):
    match: RequirementDocumentMatchRead
    requirement: RequirementRead


class TaskCreate(BaseModel):
    type: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    status: TaskStatus = "open"
    priority: str = Field(default="normal", min_length=1, max_length=32)
    blocking: bool = False
    related_requirement_id: uuid.UUID | None = None
    related_document_id: uuid.UUID | None = None
    completed_at: datetime | None = None


class TaskUpdate(BaseModel):
    type: str | None = Field(default=None, min_length=1, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: TaskStatus | None = None
    priority: str | None = Field(default=None, min_length=1, max_length=32)
    blocking: bool | None = None
    related_requirement_id: uuid.UUID | None = None
    related_document_id: uuid.UUID | None = None
    completed_at: datetime | None = None


class TaskRead(TaskCreate, ReadModel):
    id: uuid.UUID
    case_id: uuid.UUID
    created_at: datetime


class WorkflowTransitionRequest(BaseModel):
    target_state: WorkflowState
    actor: str | None = Field(default=None, min_length=1, max_length=255)
    reason: str | None = Field(default=None, min_length=1)


class WorkflowTransitionRead(ReadModel):
    id: uuid.UUID
    case_id: uuid.UUID
    from_state: WorkflowState
    to_state: WorkflowState
    actor: str | None
    reason: str | None
    created_at: datetime


class WorkflowRead(BaseModel):
    case_id: uuid.UUID
    current_state: WorkflowState
    allowed_targets: list[WorkflowState]
    history: list[WorkflowTransitionRead]


class WorkflowTransitionResult(BaseModel):
    case_id: uuid.UUID
    previous_state: WorkflowState
    current_state: WorkflowState
    transition: WorkflowTransitionRead


class NextActionRead(BaseModel):
    type: str
    title: str
    case_id: uuid.UUID
    fact_id: uuid.UUID | None = None
    fact_key: str | None = None
    requirement_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    fact_candidate_id: uuid.UUID | None = None
    import_run_id: uuid.UUID | None = None
    preparation_issue_code: str | None = None
    preparation_path: str | None = None
    target_state: WorkflowState | None = None
