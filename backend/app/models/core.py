from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SAEnum, Float, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from ..database import Base


JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowState(StrEnum):
    INTAKE = "INTAKE"
    DOCUMENTS = "DOCUMENTS"
    PREPARE = "PREPARE"
    REVIEW = "REVIEW"
    READY = "READY"
    SUBMITTED = "SUBMITTED"


class RequirementFulfillmentStatus(StrEnum):
    PENDING = "pending"
    FULFILLED = "fulfilled"
    WAIVED = "waived"


class RequirementFulfillmentSource(StrEnum):
    MANUAL = "manual"
    AUTOMATIC_DOCUMENT_EVIDENCE = "automatic_document_evidence"
    WAIVED = "waived"


class DocumentQualityState(StrEnum):
    NOT_CHECKED = "not_checked"
    CHECKING = "checking"
    PASSED = "passed"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"
    MANUAL_ACCEPTED = "manual_accepted"
    MANUAL_REJECTED = "manual_rejected"
    ERROR = "error"


class QualityCheckStatus(StrEnum):
    CHECKING = "checking"
    PASSED = "passed"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"
    ERROR = "error"


class QualityReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CompletenessStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    NOT_EVALUABLE = "not_evaluable"


class ConversationSourceType(StrEnum):
    WHATSAPP_PASTE = "whatsapp_paste"
    WHATSAPP_EXPORT = "whatsapp_export"


class ConversationParseStatus(StrEnum):
    PARSED = "parsed"
    PARSED_WITH_WARNINGS = "parsed_with_warnings"
    FAILED = "failed"


class FactExtractionRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class FactCandidateStatus(StrEnum):
    PROPOSED = "proposed"
    CONFLICT = "conflict"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class DocumentClassificationState(StrEnum):
    UNCLASSIFIED = "unclassified"
    CLASSIFICATION_PENDING = "classification_pending"
    SUGGESTION_AVAILABLE = "suggestion_available"
    CONFIRMED = "confirmed"
    CLASSIFICATION_FAILED = "classification_failed"


class ClassificationReviewStatus(StrEnum):
    PENDING = "pending"
    SUGGESTED = "suggested"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"
    FAILED = "failed"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Case(TimestampMixin, Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    visa_type: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_state: Mapped[WorkflowState] = mapped_column(
        SAEnum(
            WorkflowState,
            name="workflow_state",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            length=32,
        ),
        default=WorkflowState.INTAKE,
        nullable=False,
    )

    persons: Mapped[list[Person]] = relationship(back_populates="case", cascade="all, delete-orphan")
    facts: Mapped[list[Fact]] = relationship(back_populates="case", cascade="all, delete-orphan")
    requirements: Mapped[list[Requirement]] = relationship(back_populates="case", cascade="all, delete-orphan")
    documents: Mapped[list[Document]] = relationship(back_populates="case", cascade="all, delete-orphan")
    tasks: Mapped[list[Task]] = relationship(back_populates="case", cascade="all, delete-orphan")
    workflow_transitions: Mapped[list[WorkflowTransition]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    conversation_imports: Mapped[list[ConversationImport]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    fact_extraction_candidates: Mapped[list[FactExtractionCandidate]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


class Person(TimestampMixin, Base):
    __tablename__ = "persons"
    __table_args__ = (Index("ix_persons_case_id", "case_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_name: Mapped[str] = mapped_column(String(128), nullable=False)
    roles: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)

    case: Mapped[Case] = relationship(back_populates="persons")
    facts: Mapped[list[Fact]] = relationship(back_populates="person")
    documents: Mapped[list[Document]] = relationship(back_populates="person")
    owned_requirements: Mapped[list[Requirement]] = relationship(back_populates="owner_person")


class Fact(TimestampMixin, Base):
    __tablename__ = "facts"
    __table_args__ = (
        Index("ix_facts_case_id", "case_id"),
        Index("ix_facts_case_key", "case_id", "key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSON_TYPE, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    case: Mapped[Case] = relationship(back_populates="facts")
    person: Mapped[Person | None] = relationship(back_populates="facts")
    originating_candidates: Mapped[list[FactExtractionCandidate]] = relationship(
        back_populates="authoritative_fact",
        foreign_keys="FactExtractionCandidate.authoritative_fact_id",
    )
    conflicting_candidates: Mapped[list[FactExtractionCandidate]] = relationship(
        back_populates="conflicting_fact",
        foreign_keys="FactExtractionCandidate.conflicting_fact_id",
    )


class ConversationImport(Base):
    __tablename__ = "conversation_imports"
    __table_args__ = (
        UniqueConstraint("case_id", "content_hash", name="uq_conversation_import_content"),
        Index("ix_conversation_imports_case_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[ConversationSourceType] = mapped_column(
        SAEnum(
            ConversationSourceType,
            name="conversation_source_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
            length=32,
        ),
        nullable=False,
    )
    original_filename: Mapped[str | None] = mapped_column(String(512))
    imported_by: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    parse_status: Mapped[ConversationParseStatus] = mapped_column(
        SAEnum(
            ConversationParseStatus,
            name="conversation_parse_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
            length=32,
        ),
        nullable=False,
    )
    parse_warnings_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_TYPE, default=list, nullable=False
    )
    message_count: Mapped[int] = mapped_column(default=0, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    case: Mapped[Case] = relationship(back_populates="conversation_imports")
    messages: Mapped[list[ConversationMessage]] = relationship(
        back_populates="conversation_import", cascade="all, delete-orphan"
    )
    extraction_runs: Mapped[list[FactExtractionRun]] = relationship(
        back_populates="conversation_import", cascade="all, delete-orphan"
    )
    candidates: Mapped[list[FactExtractionCandidate]] = relationship(
        back_populates="conversation_import"
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_import_id", "sequence_number", name="uq_conversation_message_sequence"
        ),
        Index("ix_conversation_messages_import_id", "conversation_import_id"),
        Index("ix_conversation_messages_case_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_import_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation_imports.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(nullable=False)
    sender: Mapped[str | None] = mapped_column(String(255))
    message_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    conversation_import: Mapped[ConversationImport] = relationship(back_populates="messages")


class FactExtractionRun(Base):
    __tablename__ = "fact_extraction_runs"
    __table_args__ = (
        Index("ix_fact_extraction_runs_import_id", "conversation_import_id"),
        Index("ix_fact_extraction_runs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_import_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation_imports.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[FactExtractionRunStatus] = mapped_column(
        SAEnum(
            FactExtractionRunStatus,
            name="fact_extraction_run_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
            length=16,
        ),
        default=FactExtractionRunStatus.RUNNING,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(128))
    candidate_count: Mapped[int] = mapped_column(default=0, nullable=False)
    rejected_output_count: Mapped[int] = mapped_column(default=0, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation_import: Mapped[ConversationImport] = relationship(
        back_populates="extraction_runs"
    )
    candidates: Mapped[list[FactExtractionCandidate]] = relationship(
        back_populates="extraction_run"
    )


class FactExtractionCandidate(Base):
    __tablename__ = "fact_extraction_candidates"
    __table_args__ = (
        Index("ix_fact_candidates_case_id", "case_id"),
        Index("ix_fact_candidates_import_id", "conversation_import_id"),
        Index("ix_fact_candidates_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    conversation_import_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversation_imports.id", ondelete="SET NULL")
    )
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fact_extraction_runs.id", ondelete="SET NULL")
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSON_TYPE, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_ids_json: Mapped[list[str]] = mapped_column(
        JSON_TYPE, default=list, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[FactCandidateStatus] = mapped_column(
        SAEnum(
            FactCandidateStatus,
            name="fact_candidate_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
            length=16,
        ),
        nullable=False,
    )
    conflicting_fact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("facts.id", ondelete="SET NULL")
    )
    authoritative_fact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("facts.id", ondelete="SET NULL")
    )
    corrected_value_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    review_reason: Mapped[str | None] = mapped_column(Text)

    case: Mapped[Case] = relationship(back_populates="fact_extraction_candidates")
    conversation_import: Mapped[ConversationImport | None] = relationship(
        back_populates="candidates"
    )
    extraction_run: Mapped[FactExtractionRun | None] = relationship(back_populates="candidates")
    conflicting_fact: Mapped[Fact | None] = relationship(
        back_populates="conflicting_candidates", foreign_keys=[conflicting_fact_id]
    )
    authoritative_fact: Mapped[Fact | None] = relationship(
        back_populates="originating_candidates", foreign_keys=[authoritative_fact_id]
    )


class Requirement(TimestampMixin, Base):
    __tablename__ = "requirements"
    __table_args__ = (Index("ix_requirements_case_id", "case_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    document_type: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_role: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    requirement_level: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    is_blocking: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fulfillment_status: Mapped[RequirementFulfillmentStatus] = mapped_column(
        SAEnum(
            RequirementFulfillmentStatus,
            name="requirement_fulfillment_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
            length=16,
        ),
        default=RequirementFulfillmentStatus.PENDING,
        nullable=False,
    )
    fulfillment_source: Mapped[RequirementFulfillmentSource | None] = mapped_column(
        SAEnum(
            RequirementFulfillmentSource,
            name="requirement_fulfillment_source",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
            length=32,
        )
    )
    fulfillment_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completeness_policy_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        default=lambda: {"mode": "single_document"},
        nullable=False,
    )
    waiver_reason: Mapped[str | None] = mapped_column(Text)
    waived_by: Mapped[str | None] = mapped_column(String(255))
    waived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    case: Mapped[Case] = relationship(back_populates="requirements")
    owner_person: Mapped[Person | None] = relationship(back_populates="owned_requirements")
    tasks: Mapped[list[Task]] = relationship(back_populates="related_requirement")
    document_matches: Mapped[list[RequirementDocumentMatch]] = relationship(
        back_populates="requirement", cascade="all, delete-orphan"
    )
    completeness_evaluations: Mapped[list[RequirementCompletenessEvaluation]] = relationship(
        back_populates="requirement", cascade="all, delete-orphan"
    )
    fulfillment_events: Mapped[list[RequirementFulfillmentEvent]] = relationship(
        back_populates="requirement", cascade="all, delete-orphan"
    )


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_case_id", "case_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    document_type: Mapped[str | None] = mapped_column(String(128))
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    classification_status: Mapped[DocumentClassificationState] = mapped_column(
        SAEnum(
            DocumentClassificationState,
            name="document_classification_state",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
            length=32,
        ),
        default=DocumentClassificationState.UNCLASSIFIED,
        nullable=False,
    )
    quality_status: Mapped[DocumentQualityState] = mapped_column(
        SAEnum(
            DocumentQualityState,
            name="document_quality_state",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
            length=32,
        ),
        default=DocumentQualityState.NOT_CHECKED,
        nullable=False,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)

    case: Mapped[Case] = relationship(back_populates="documents")
    person: Mapped[Person | None] = relationship(back_populates="documents")
    tasks: Mapped[list[Task]] = relationship(back_populates="related_document")
    requirement_matches: Mapped[list[RequirementDocumentMatch]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    classifications: Mapped[list[DocumentClassification]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    quality_checks: Mapped[list[DocumentQualityCheck]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentClassification(Base):
    __tablename__ = "document_classifications"
    __table_args__ = (
        Index("ix_document_classifications_document_id", "document_id"),
        Index("ix_document_classifications_created_at", "created_at"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="classification_confidence_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    suggested_document_type: Mapped[str | None] = mapped_column(String(128))
    suggested_person_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("persons.id", ondelete="SET NULL")
    )
    extracted_owner_name: Mapped[str | None] = mapped_column(String(255))
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[list[dict[str, str]]] = mapped_column(
        JSON_TYPE, default=list, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(128))
    document_hash: Mapped[str | None] = mapped_column(String(64))
    raw_result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    status: Mapped[ClassificationReviewStatus] = mapped_column(
        SAEnum(
            ClassificationReviewStatus,
            name="classification_review_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
            length=16,
        ),
        default=ClassificationReviewStatus.PENDING,
        nullable=False,
    )
    failure_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    corrected_document_type: Mapped[str | None] = mapped_column(String(128))
    corrected_person_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("persons.id", ondelete="SET NULL")
    )

    document: Mapped[Document] = relationship(back_populates="classifications")
    suggested_person: Mapped[Person | None] = relationship(
        foreign_keys=[suggested_person_id]
    )
    corrected_person: Mapped[Person | None] = relationship(
        foreign_keys=[corrected_person_id]
    )


class RequirementDocumentMatch(Base):
    __tablename__ = "requirement_document_matches"
    __table_args__ = (
        UniqueConstraint(
            "requirement_id", "document_id", name="uq_requirement_document_match"
        ),
        Index("ix_requirement_document_matches_requirement_id", "requirement_id"),
        Index("ix_requirement_document_matches_document_id", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    requirement: Mapped[Requirement] = relationship(back_populates="document_matches")
    document: Mapped[Document] = relationship(back_populates="requirement_matches")


class DocumentQualityCheck(Base):
    __tablename__ = "document_quality_checks"
    __table_args__ = (
        Index("ix_document_quality_checks_document_id", "document_id"),
        Index("ix_document_quality_checks_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[QualityCheckStatus] = mapped_column(
        SAEnum(
            QualityCheckStatus,
            name="quality_check_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
            length=16,
        ),
        default=QualityCheckStatus.CHECKING,
        nullable=False,
    )
    checks_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    issues_json: Mapped[list[dict[str, str]]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    extracted_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluator_version: Mapped[str | None] = mapped_column(String(128))
    document_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    review_decision: Mapped[QualityReviewDecision | None] = mapped_column(
        SAEnum(
            QualityReviewDecision,
            name="quality_review_decision",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
            length=16,
        )
    )
    review_reason: Mapped[str | None] = mapped_column(Text)

    document: Mapped[Document] = relationship(back_populates="quality_checks")


class RequirementCompletenessEvaluation(Base):
    __tablename__ = "requirement_completeness_evaluations"
    __table_args__ = (
        Index("ix_requirement_completeness_requirement_id", "requirement_id"),
        Index("ix_requirement_completeness_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[CompletenessStatus] = mapped_column(
        SAEnum(
            CompletenessStatus,
            name="requirement_completeness_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
            length=16,
        ),
        nullable=False,
    )
    matched_document_ids_json: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    accepted_document_ids_json: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    matched_count: Mapped[int] = mapped_column(default=0, nullable=False)
    accepted_count: Mapped[int] = mapped_column(default=0, nullable=False)
    coverage_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    missing_json: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    trigger: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    requirement: Mapped[Requirement] = relationship(back_populates="completeness_evaluations")


class RequirementFulfillmentEvent(Base):
    __tablename__ = "requirement_fulfillment_events"
    __table_args__ = (Index("ix_requirement_fulfillment_events_requirement_id", "requirement_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str] = mapped_column(String(16), nullable=False)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[RequirementFulfillmentSource] = mapped_column(
        SAEnum(
            RequirementFulfillmentSource,
            name="fulfillment_event_source",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
            length=32,
        ),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str | None] = mapped_column(String(255))
    document_ids_json: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    requirement: Mapped[Requirement] = relationship(back_populates="fulfillment_events")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_case_id", "case_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    priority: Mapped[str] = mapped_column(String(32), default="normal", nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    related_requirement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("requirements.id", ondelete="SET NULL"))
    related_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    case: Mapped[Case] = relationship(back_populates="tasks")
    related_requirement: Mapped[Requirement | None] = relationship(back_populates="tasks")
    related_document: Mapped[Document | None] = relationship(back_populates="tasks")


class WorkflowTransition(Base):
    __tablename__ = "workflow_transitions"
    __table_args__ = (Index("ix_workflow_transitions_case_id", "case_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    from_state: Mapped[WorkflowState] = mapped_column(
        SAEnum(
            WorkflowState,
            name="workflow_transition_from_state",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            length=32,
        ),
        nullable=False,
    )
    to_state: Mapped[WorkflowState] = mapped_column(
        SAEnum(
            WorkflowState,
            name="workflow_transition_to_state",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            length=32,
        ),
        nullable=False,
    )
    actor: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    case: Mapped[Case] = relationship(back_populates="workflow_transitions")
