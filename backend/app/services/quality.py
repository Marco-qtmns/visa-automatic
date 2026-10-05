from __future__ import annotations

import hashlib
import io
import re
import uuid
from datetime import datetime, timezone

import pymupdf
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..quality_evaluators import (
    QualityCheckFinding,
    QualityContent,
    TypeSpecificQualityEvaluator,
)
from ..schemas import core as schemas
from ..storage import StorageProvider
from .core import CoreDataService, DomainNotFound, DomainValidationError
from .documents import DocumentMatchingService
from .quality_config import DEFAULT_QUALITY_PROFILES


MAX_QUALITY_TEXT_CHARS = 12_000
ACCEPTABLE_QUALITY_STATES = frozenset({
    models.DocumentQualityState.PASSED,
    models.DocumentQualityState.MANUAL_ACCEPTED,
})


class DocumentQualityService:
    """Evaluates one immutable uploaded document and preserves every attempt."""

    def __init__(
        self,
        session: Session,
        storage: StorageProvider,
        evaluator: TypeSpecificQualityEvaluator,
    ):
        self.session = session
        self.storage = storage
        self.evaluator = evaluator
        self.core = CoreDataService(session)

    def run(self, document_id: uuid.UUID) -> models.DocumentQualityCheck:
        document = self.core.get_document(document_id)
        attempt = models.DocumentQualityCheck(
            document_id=document.id,
            status=models.QualityCheckStatus.CHECKING,
            checks_json=[],
            issues_json=[],
            extracted_metadata_json={},
            provider=self.evaluator.name[:64],
            evaluator_version=(self.evaluator.version or None)[:128]
            if self.evaluator.version else None,
        )
        document.quality_status = models.DocumentQualityState.CHECKING
        self.session.add(attempt)
        self.session.commit()
        self.session.refresh(attempt)

        try:
            content, findings = self._technical_inspection(document)
            metadata: dict[str, object] = {}
            if not any(item.status == "fail" for item in findings):
                if document.document_type is None:
                    findings.append(QualityCheckFinding(
                        check_id="document_type_assigned",
                        status="manual_review",
                        evidence=None,
                        issue="Assign an authoritative document type before type-specific quality review",
                        evaluator="deterministic",
                    ))
                else:
                    configured = DEFAULT_QUALITY_PROFILES[document.document_type]
                    result = self.evaluator.evaluate(content, configured)
                    findings.extend(result.checks)
                    metadata = self._safe_metadata(result.extracted_metadata)
            checks = [self._validated_finding(item) for item in findings]
            attempt.checks_json = checks
            attempt.issues_json = [
                {"check_id": item["check_id"], "message": item["issue"]}
                for item in checks if item.get("issue")
            ]
            attempt.extracted_metadata_json = metadata
            attempt.document_hash = content.document_hash
            attempt.status = self._summary_status(checks)
            document.quality_status = self._document_state(attempt.status)
            self.session.commit()
        except Exception:
            self.session.rollback()
            attempt = self.session.get(models.DocumentQualityCheck, attempt.id)
            document = self.core.get_document(document_id)
            if attempt is None:
                raise
            attempt.status = models.QualityCheckStatus.ERROR
            attempt.issues_json = [{
                "check_id": "quality_execution",
                "message": "Quality analysis could not be completed",
            }]
            document.quality_status = models.DocumentQualityState.ERROR
            self.session.commit()
        self.session.refresh(attempt)
        RequirementCompletenessService(self.session).evaluate_for_document(
            document_id, trigger="quality_check"
        )
        return attempt

    def list_checks(self, document_id: uuid.UUID) -> list[models.DocumentQualityCheck]:
        self.core.get_document(document_id)
        return list(self.session.scalars(
            select(models.DocumentQualityCheck)
            .where(models.DocumentQualityCheck.document_id == document_id)
            .order_by(
                models.DocumentQualityCheck.created_at.desc(),
                models.DocumentQualityCheck.id.desc(),
            )
        ))

    def accept(
        self,
        document_id: uuid.UUID,
        check_id: uuid.UUID,
        payload: schemas.QualityManualReview,
    ) -> models.DocumentQualityCheck:
        attempt, document = self._reviewable(document_id, check_id)
        attempt.review_decision = models.QualityReviewDecision.ACCEPTED
        attempt.reviewed_by = payload.reviewed_by
        attempt.review_reason = payload.reason
        attempt.reviewed_at = datetime.now(timezone.utc)
        document.quality_status = models.DocumentQualityState.MANUAL_ACCEPTED
        self.session.commit()
        self.session.refresh(attempt)
        RequirementCompletenessService(self.session).evaluate_for_document(
            document_id, trigger="quality_manual_accept"
        )
        return attempt

    def reject(
        self,
        document_id: uuid.UUID,
        check_id: uuid.UUID,
        payload: schemas.QualityManualReview,
    ) -> models.DocumentQualityCheck:
        attempt, document = self._reviewable(document_id, check_id)
        attempt.review_decision = models.QualityReviewDecision.REJECTED
        attempt.reviewed_by = payload.reviewed_by
        attempt.review_reason = payload.reason
        attempt.reviewed_at = datetime.now(timezone.utc)
        document.quality_status = models.DocumentQualityState.MANUAL_REJECTED
        self.session.commit()
        self.session.refresh(attempt)
        RequirementCompletenessService(self.session).evaluate_for_document(
            document_id, trigger="quality_manual_reject"
        )
        return attempt

    def _reviewable(
        self, document_id: uuid.UUID, check_id: uuid.UUID
    ) -> tuple[models.DocumentQualityCheck, models.Document]:
        document = self.core.get_document(document_id)
        attempt = self.session.get(models.DocumentQualityCheck, check_id)
        if attempt is None or attempt.document_id != document_id:
            raise DomainNotFound("DocumentQualityCheck not found")
        latest = self.list_checks(document_id)[0]
        if latest.id != attempt.id:
            raise DomainValidationError("only the latest quality check can be reviewed")
        if attempt.status == models.QualityCheckStatus.CHECKING:
            raise DomainValidationError("quality check is still running")
        if attempt.review_decision is not None:
            raise DomainValidationError("quality check has already been reviewed; run a new check")
        return attempt, document

    def _technical_inspection(
        self, document: models.Document
    ) -> tuple[QualityContent, list[QualityCheckFinding]]:
        try:
            with self.storage.open(document.storage_path) as stream:
                binary = stream.read()
        except Exception as error:
            raise DomainValidationError("stored document could not be read") from error
        document_hash = hashlib.sha256(binary).hexdigest()
        findings = [QualityCheckFinding(
            check_id="stored_file_accessible",
            status="pass",
            evidence=f"Stored file bytes read: {len(binary)}",
            issue=None,
            evaluator="deterministic",
        )]
        text = ""
        page_count: int | None = None
        width: int | None = None
        height: int | None = None

        if document.mime_type == "application/pdf":
            try:
                with pymupdf.open(stream=binary, filetype="pdf") as pdf:
                    page_count = pdf.page_count
                    if page_count < 1:
                        raise ValueError("PDF contains no pages")
                    remaining = MAX_QUALITY_TEXT_CHARS
                    parts: list[str] = []
                    for page in pdf:
                        if remaining <= 0:
                            break
                        value = page.get_text("text")[:remaining]
                        parts.append(value)
                        remaining -= len(value)
                    text = "\n".join(parts).strip()
                findings.append(QualityCheckFinding(
                    check_id="pdf_decodable",
                    status="pass",
                    evidence=f"PDF opened successfully; page count: {page_count}",
                    issue=None,
                    evaluator="deterministic",
                ))
            except Exception:
                findings.append(QualityCheckFinding(
                    check_id="pdf_decodable",
                    status="fail",
                    evidence=None,
                    issue="PDF could not be opened or contains no pages",
                    evaluator="deterministic",
                ))
        elif document.mime_type in {"image/jpeg", "image/png"}:
            try:
                with Image.open(io.BytesIO(binary)) as image:
                    width, height = image.size
                    image.verify()
                findings.append(QualityCheckFinding(
                    check_id="image_decodable",
                    status="pass",
                    evidence=f"Image decoded successfully; dimensions: {width} × {height}",
                    issue=None,
                    evaluator="deterministic",
                ))
            except (UnidentifiedImageError, OSError, ValueError):
                findings.append(QualityCheckFinding(
                    check_id="image_decodable",
                    status="fail",
                    evidence=None,
                    issue="Image could not be decoded",
                    evaluator="deterministic",
                ))
        else:
            findings.append(QualityCheckFinding(
                check_id="supported_file_format",
                status="fail",
                evidence=None,
                issue="File format is not supported for quality inspection",
                evaluator="deterministic",
            ))
        return QualityContent(
            text=text,
            page_count=page_count,
            mime_type=document.mime_type,
            binary_content=binary,
            document_hash=document_hash,
            image_width=width,
            image_height=height,
        ), findings

    @staticmethod
    def _validated_finding(finding: QualityCheckFinding) -> dict[str, object]:
        return schemas.QualityCheckResult.model_validate({
            "check_id": finding.check_id,
            "status": finding.status,
            "evidence": finding.evidence,
            "issue": finding.issue,
            "evaluator": finding.evaluator,
            "confidence": finding.confidence,
        }).model_dump()

    @staticmethod
    def _safe_metadata(value: dict[str, object]) -> dict[str, object]:
        allowed = {"account_holder_candidate", "statement_period_candidates", "coverage_months"}
        return {key: item for key, item in value.items() if key in allowed}

    @staticmethod
    def _summary_status(checks: list[dict[str, object]]) -> models.QualityCheckStatus:
        statuses = {item["status"] for item in checks}
        if "fail" in statuses:
            return models.QualityCheckStatus.FAILED
        if statuses & {"manual_review", "unknown"}:
            return models.QualityCheckStatus.MANUAL_REVIEW
        return models.QualityCheckStatus.PASSED

    @staticmethod
    def _document_state(status: models.QualityCheckStatus) -> models.DocumentQualityState:
        return {
            models.QualityCheckStatus.CHECKING: models.DocumentQualityState.CHECKING,
            models.QualityCheckStatus.PASSED: models.DocumentQualityState.PASSED,
            models.QualityCheckStatus.FAILED: models.DocumentQualityState.FAILED,
            models.QualityCheckStatus.MANUAL_REVIEW: models.DocumentQualityState.MANUAL_REVIEW,
            models.QualityCheckStatus.ERROR: models.DocumentQualityState.ERROR,
        }[status]


class RequirementCompletenessService:
    """Evaluates accepted matched evidence separately from per-file quality."""

    def __init__(self, session: Session):
        self.session = session
        self.core = CoreDataService(session)

    def evaluate(
        self, requirement_id: uuid.UUID, *, trigger: str = "explicit"
    ) -> models.RequirementCompletenessEvaluation:
        requirement = self.core.get_requirement(requirement_id)
        matches = list(self.session.scalars(
            select(models.RequirementDocumentMatch)
            .where(models.RequirementDocumentMatch.requirement_id == requirement_id)
            .order_by(models.RequirementDocumentMatch.created_at, models.RequirementDocumentMatch.id)
        ))
        documents = [match.document for match in matches]
        matching = DocumentMatchingService(self.session)
        accepted = [
            document for document in documents
            if document.quality_status in ACCEPTABLE_QUALITY_STATES
            and matching._compatible(requirement, document)[0]
        ]

        policy = schemas.validate_completeness_policy(requirement.completeness_policy_json)
        coverage: dict[str, object] = {}
        missing: list[str] = []
        if not requirement.active:
            status = models.CompletenessStatus.NOT_EVALUABLE
            explanation = "Requirement is inactive"
        elif policy["mode"] == "single_document":
            status = (
                models.CompletenessStatus.COMPLETE
                if accepted else models.CompletenessStatus.INCOMPLETE
            )
            if accepted:
                explanation = "At least one compatible matched document has acceptable quality"
            else:
                explanation = "No compatible matched document has acceptable quality"
                missing = ["accepted_document"]
        else:
            required_months = set(policy["required_months"])
            covered_months: set[str] = set()
            for document in accepted:
                latest = self._latest_quality_check(document.id)
                if latest is None:
                    continue
                values = latest.extracted_metadata_json.get("coverage_months", [])
                if isinstance(values, list):
                    covered_months.update(
                        value for value in values
                        if isinstance(value, str)
                        and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value)
                    )
            missing = sorted(required_months - covered_months)
            coverage = {
                "required_months": sorted(required_months),
                "covered_months": sorted(covered_months),
            }
            status = (
                models.CompletenessStatus.COMPLETE
                if not missing else models.CompletenessStatus.INCOMPLETE
            )
            explanation = (
                "All explicitly required statement months are covered"
                if not missing
                else "Statement month coverage is incomplete"
            )

        evaluation = models.RequirementCompletenessEvaluation(
            requirement_id=requirement.id,
            status=status,
            matched_document_ids_json=[str(document.id) for document in documents],
            accepted_document_ids_json=[str(document.id) for document in accepted],
            matched_count=len(documents),
            accepted_count=len(accepted),
            coverage_json=coverage,
            missing_json=missing,
            explanation=explanation,
            trigger=trigger[:64],
        )
        self.session.add(evaluation)
        self._apply_fulfillment(requirement, evaluation, accepted)
        self.session.commit()
        self.session.refresh(evaluation)
        return evaluation

    def evaluate_for_document(self, document_id: uuid.UUID, *, trigger: str) -> list[models.RequirementCompletenessEvaluation]:
        requirement_ids = list(self.session.scalars(
            select(models.RequirementDocumentMatch.requirement_id)
            .where(models.RequirementDocumentMatch.document_id == document_id)
        ))
        return [self.evaluate(requirement_id, trigger=trigger) for requirement_id in requirement_ids]

    def list_evaluations(
        self, requirement_id: uuid.UUID
    ) -> list[models.RequirementCompletenessEvaluation]:
        self.core.get_requirement(requirement_id)
        return list(self.session.scalars(
            select(models.RequirementCompletenessEvaluation)
            .where(models.RequirementCompletenessEvaluation.requirement_id == requirement_id)
            .order_by(
                models.RequirementCompletenessEvaluation.created_at.desc(),
                models.RequirementCompletenessEvaluation.id.desc(),
            )
        ))

    def list_fulfillment_events(
        self, requirement_id: uuid.UUID
    ) -> list[models.RequirementFulfillmentEvent]:
        self.core.get_requirement(requirement_id)
        return list(self.session.scalars(
            select(models.RequirementFulfillmentEvent)
            .where(models.RequirementFulfillmentEvent.requirement_id == requirement_id)
            .order_by(models.RequirementFulfillmentEvent.created_at, models.RequirementFulfillmentEvent.id)
        ))

    def _latest_quality_check(self, document_id: uuid.UUID) -> models.DocumentQualityCheck | None:
        return self.session.scalar(
            select(models.DocumentQualityCheck)
            .where(models.DocumentQualityCheck.document_id == document_id)
            .order_by(
                models.DocumentQualityCheck.created_at.desc(),
                models.DocumentQualityCheck.id.desc(),
            )
            .limit(1)
        )

    def _apply_fulfillment(
        self,
        requirement: models.Requirement,
        evaluation: models.RequirementCompletenessEvaluation,
        accepted: list[models.Document],
    ) -> None:
        if not requirement.active:
            return
        if requirement.fulfillment_status == models.RequirementFulfillmentStatus.WAIVED:
            return
        if (
            requirement.fulfillment_status == models.RequirementFulfillmentStatus.FULFILLED
            and requirement.fulfillment_source != models.RequirementFulfillmentSource.AUTOMATIC_DOCUMENT_EVIDENCE
        ):
            return
        target = (
            models.RequirementFulfillmentStatus.FULFILLED
            if evaluation.status == models.CompletenessStatus.COMPLETE
            else models.RequirementFulfillmentStatus.PENDING
        )
        if target == requirement.fulfillment_status:
            return
        previous = requirement.fulfillment_status
        requirement.fulfillment_status = target
        requirement.fulfillment_source = (
            models.RequirementFulfillmentSource.AUTOMATIC_DOCUMENT_EVIDENCE
            if target == models.RequirementFulfillmentStatus.FULFILLED else None
        )
        requirement.fulfillment_updated_at = datetime.now(timezone.utc)
        self.session.add(models.RequirementFulfillmentEvent(
            requirement_id=requirement.id,
            from_status=previous.value,
            to_status=target.value,
            source=models.RequirementFulfillmentSource.AUTOMATIC_DOCUMENT_EVIDENCE,
            reason=evaluation.explanation,
            document_ids_json=[str(document.id) for document in accepted],
        ))
