from __future__ import annotations

import hashlib
import math
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Protocol

import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..classifiers import (
    ClassificationEvidenceItem,
    ClassificationProviderUnavailable,
    ClassifierResult,
    DocumentClassifier,
    ExtractedDocumentContent,
)
from ..schemas import core as schemas
from ..storage import StorageProvider
from .core import CoreDataService, DomainNotFound, DomainValidationError
from .documents import DocumentMatchingService
from .requirements import DEFAULT_RULE_CATALOG


MAX_EXTRACTED_TEXT_CHARS = 12_000
MAX_EVIDENCE_ITEMS = 10


class ContentExtractionError(RuntimeError):
    pass


class DocumentContentExtractor(Protocol):
    def extract(
        self, document: models.Document, storage: StorageProvider
    ) -> ExtractedDocumentContent: ...


class DefaultDocumentContentExtractor:
    """Extract embedded PDF text; retain in-memory bytes for image/vision providers."""

    def extract(
        self, document: models.Document, storage: StorageProvider
    ) -> ExtractedDocumentContent:
        try:
            with storage.open(document.storage_path) as stream:
                binary = stream.read()
        except Exception as error:
            raise ContentExtractionError("stored document could not be read") from error

        text = ""
        page_count: int | None = None
        if document.mime_type == "application/pdf":
            try:
                with pymupdf.open(stream=binary, filetype="pdf") as pdf:
                    page_count = pdf.page_count
                    pieces: list[str] = []
                    remaining = MAX_EXTRACTED_TEXT_CHARS
                    for page in pdf:
                        if remaining <= 0:
                            break
                        value = page.get_text("text")[:remaining]
                        pieces.append(value)
                        remaining -= len(value)
                    text = "\n".join(pieces).strip()
            except Exception as error:
                raise ContentExtractionError("PDF content could not be extracted") from error

        return ExtractedDocumentContent(
            text=text,
            page_count=page_count,
            mime_type=document.mime_type,
            binary_content=binary,
            document_hash=hashlib.sha256(binary).hexdigest(),
        )


def _normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class DocumentClassificationService:
    """Explicit suggestion lifecycle; authoritative metadata changes only on review."""

    def __init__(
        self,
        session: Session,
        storage: StorageProvider,
        classifier: DocumentClassifier,
        extractor: DocumentContentExtractor | None = None,
    ):
        self.session = session
        self.storage = storage
        self.classifier = classifier
        self.extractor = extractor or DefaultDocumentContentExtractor()
        self.core = CoreDataService(session)

    def classify(self, document_id: uuid.UUID) -> models.DocumentClassification:
        document = self.core.get_document(document_id)
        attempt = models.DocumentClassification(
            document_id=document.id,
            provider=self.classifier.name[:64],
            model_version=(self.classifier.model_version or None)[:128] if self.classifier.model_version else None,
            status=models.ClassificationReviewStatus.PENDING,
            evidence_json=[],
        )
        document.classification_status = models.DocumentClassificationState.CLASSIFICATION_PENDING
        self.session.add(attempt)
        self.session.commit()
        self.session.refresh(attempt)

        try:
            content = self.extractor.extract(document, self.storage)
            result = self.classifier.classify(content)
            document_type, evidence, raw_result = self._validated_result(result)
            person_id, owner_evidence = self._resolve_owner(
                document.case_id, result.owner_name
            )
            evidence.extend(owner_evidence)
            attempt.suggested_document_type = document_type
            attempt.suggested_person_id = person_id
            attempt.extracted_owner_name = (
                result.owner_name.strip()[:255] if result.owner_name else None
            )
            attempt.confidence = self._confidence(result.confidence)
            attempt.evidence_json = evidence[:MAX_EVIDENCE_ITEMS]
            attempt.document_hash = content.document_hash
            attempt.raw_result_json = raw_result
            attempt.status = models.ClassificationReviewStatus.SUGGESTED
            document.classification_status = models.DocumentClassificationState.SUGGESTION_AVAILABLE
            self.session.commit()
        except Exception as error:
            self.session.rollback()
            attempt = self.session.get(models.DocumentClassification, attempt.id)
            document = self.core.get_document(document_id)
            if attempt is None:
                raise
            attempt.status = models.ClassificationReviewStatus.FAILED
            attempt.failure_reason = self._safe_failure_reason(error)
            document.classification_status = models.DocumentClassificationState.CLASSIFICATION_FAILED
            self.session.commit()
        self.session.refresh(attempt)
        return attempt

    def list_classifications(
        self, document_id: uuid.UUID
    ) -> list[models.DocumentClassification]:
        self.core.get_document(document_id)
        return list(self.session.scalars(
            select(models.DocumentClassification)
            .where(models.DocumentClassification.document_id == document_id)
            .order_by(
                models.DocumentClassification.created_at.desc(),
                models.DocumentClassification.id.desc(),
            )
        ))

    def accept(
        self,
        document_id: uuid.UUID,
        classification_id: uuid.UUID,
        reviewed_by: str,
    ) -> models.DocumentClassification:
        attempt = self._reviewable(document_id, classification_id)
        changes: dict[str, object] = {}
        if attempt.suggested_document_type is not None:
            changes["document_type"] = attempt.suggested_document_type
        if attempt.suggested_person_id is not None:
            changes["person_id"] = attempt.suggested_person_id
        if not changes:
            raise DomainValidationError("classification has no metadata suggestion to accept")
        DocumentMatchingService(self.session).update_document(
            document_id, schemas.DocumentUpdate(**changes), commit=False
        )
        self._finish_review(attempt, models.ClassificationReviewStatus.ACCEPTED, reviewed_by)
        return attempt

    def correct(
        self,
        document_id: uuid.UUID,
        classification_id: uuid.UUID,
        payload: schemas.ClassificationCorrection,
    ) -> models.DocumentClassification:
        attempt = self._reviewable(document_id, classification_id)
        if payload.document_type not in DEFAULT_RULE_CATALOG.document_types:
            raise DomainValidationError(f"unknown document type: {payload.document_type}")
        DocumentMatchingService(self.session).update_document(
            document_id,
            schemas.DocumentUpdate(
                document_type=payload.document_type, person_id=payload.person_id
            ),
            commit=False,
        )
        attempt.corrected_document_type = payload.document_type
        attempt.corrected_person_id = payload.person_id
        self._finish_review(
            attempt, models.ClassificationReviewStatus.CORRECTED, payload.reviewed_by
        )
        return attempt

    def reject(
        self,
        document_id: uuid.UUID,
        classification_id: uuid.UUID,
        reviewed_by: str,
    ) -> models.DocumentClassification:
        attempt = self._reviewable(document_id, classification_id)
        self._finish_review(attempt, models.ClassificationReviewStatus.REJECTED, reviewed_by)
        return attempt

    def _reviewable(
        self, document_id: uuid.UUID, classification_id: uuid.UUID
    ) -> models.DocumentClassification:
        self.core.get_document(document_id)
        attempt = self.session.get(models.DocumentClassification, classification_id)
        if attempt is None or attempt.document_id != document_id:
            raise DomainNotFound("DocumentClassification not found")
        if attempt.status != models.ClassificationReviewStatus.SUGGESTED:
            raise DomainValidationError("classification is not awaiting review")
        return attempt

    def _finish_review(
        self,
        attempt: models.DocumentClassification,
        status: models.ClassificationReviewStatus,
        reviewed_by: str,
    ) -> None:
        attempt.status = status
        attempt.reviewed_by = reviewed_by
        attempt.reviewed_at = datetime.now(timezone.utc)
        self.session.flush()
        document = self.core.get_document(attempt.document_id)
        latest = self.session.scalar(
            select(models.DocumentClassification)
            .where(models.DocumentClassification.document_id == attempt.document_id)
            .order_by(
                models.DocumentClassification.created_at.desc(),
                models.DocumentClassification.id.desc(),
            )
        )
        if latest is not None:
            document.classification_status = {
                models.ClassificationReviewStatus.PENDING: models.DocumentClassificationState.CLASSIFICATION_PENDING,
                models.ClassificationReviewStatus.SUGGESTED: models.DocumentClassificationState.SUGGESTION_AVAILABLE,
                models.ClassificationReviewStatus.ACCEPTED: models.DocumentClassificationState.CONFIRMED,
                models.ClassificationReviewStatus.CORRECTED: models.DocumentClassificationState.CONFIRMED,
                models.ClassificationReviewStatus.REJECTED: models.DocumentClassificationState.UNCLASSIFIED,
                models.ClassificationReviewStatus.FAILED: models.DocumentClassificationState.CLASSIFICATION_FAILED,
            }[latest.status]
        self.session.commit()
        self.session.refresh(attempt)

    def _validated_result(
        self, result: ClassifierResult
    ) -> tuple[str | None, list[dict[str, str]], dict[str, object | None]]:
        evidence = [
            schemas.ClassificationEvidence.model_validate({
                "type": item.type,
                "value": item.value,
            }).model_dump()
            for item in result.evidence[:MAX_EVIDENCE_ITEMS]
        ]
        document_type = result.document_type
        if document_type not in DEFAULT_RULE_CATALOG.document_types:
            if document_type is not None:
                evidence.append({
                    "type": "classification",
                    "value": "Classifier output did not map to the document type catalog",
                })
            document_type = None
        raw_result: dict[str, object | None] = {
            "document_type": result.document_type[:128] if result.document_type else None,
            "owner_name": result.owner_name[:255] if result.owner_name else None,
            "confidence": self._confidence(result.confidence),
        }
        return document_type, evidence, raw_result

    def _resolve_owner(
        self, case_id: uuid.UUID, owner_name: str | None
    ) -> tuple[uuid.UUID | None, list[dict[str, str]]]:
        if not owner_name or not owner_name.strip():
            return None, [{
                "type": "owner_resolution",
                "value": "No owner identity was detected",
            }]
        normalized = _normalized_name(owner_name)
        matches = [
            person for person in self.core.list_persons(case_id)
            if _normalized_name(f"{person.first_name} {person.last_name}") == normalized
        ]
        if len(matches) == 1:
            return matches[0].id, [{
                "type": "owner_resolution",
                "value": "Extracted owner name uniquely matched a person in this case",
            }]
        if len(matches) > 1:
            return None, [{
                "type": "owner_resolution",
                "value": "Extracted owner name matched multiple people in this case",
            }]
        return None, [{
            "type": "owner_resolution",
            "value": "Extracted owner name did not match a person in this case",
        }]

    @staticmethod
    def _confidence(value: float | None) -> float | None:
        if value is None:
            return None
        number = float(value)
        if not math.isfinite(number):
            raise DomainValidationError("classifier confidence must be finite")
        return min(1.0, max(0.0, number))

    @staticmethod
    def _safe_failure_reason(error: Exception) -> str:
        if isinstance(error, ClassificationProviderUnavailable):
            return "Classification provider is not configured or supported."
        if isinstance(error, ContentExtractionError):
            return "Document content could not be extracted."
        return "Classification provider returned an invalid result or failed."
