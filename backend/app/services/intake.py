from __future__ import annotations

import hashlib
import io
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import PurePath

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from canada.models import CanadaCase

from .. import models
from ..config.canada_import_mapping import MAPPING_VERSION
from ..models import canada as cm
from ..models.intake import IntakeProcessingAttempt, IntakeSubmission
from ..schemas.core import CaseCreate
from ..storage import StorageObjectNotFound, StorageProvider
from .audit import record_audit
from .canada_imports import CanadaLegacyImportService, SOURCE_LIMITS, VerifiedGoogleImportAdapter
from .core import DomainNotFound, DomainValidationError
from .requirements import CaseApplicationService


LOGGER = logging.getLogger(__name__)
GOOGLE_FORMS_CSV = "GOOGLE_FORMS_CSV"
UNIDENTIFIED_APPLICANT = "Applicant not identified yet"


class AmbiguousCaseMatch(DomainValidationError):
    pass


class IntakeSourceAdapter(ABC):
    source_type: str
    max_bytes: int

    @abstractmethod
    def parse_source(self, content: bytes, filename: str) -> object: ...

    def identify_submission(self, content: bytes, external_id: str | None) -> str:
        return external_id or hashlib.sha256(content).hexdigest()

    def normalize(self, parsed: object) -> object:
        return parsed

    def validate_source(self, parsed: object) -> None:
        if parsed is None:
            raise DomainValidationError("source did not produce an intake record")

    @abstractmethod
    def create_import(
        self, session: Session, submission: IntakeSubmission, parsed: object, actor_email: str | None
    ) -> cm.CanadaLegacyImportRun: ...


class GoogleFormsCsvIntakeAdapter(IntakeSourceAdapter):
    source_type = GOOGLE_FORMS_CSV
    max_bytes = SOURCE_LIMITS["google_verified_csv"]

    def __init__(self) -> None:
        self.legacy = VerifiedGoogleImportAdapter()

    def parse_source(self, content: bytes, filename: str) -> CanadaCase:
        return self.legacy.parse(content, filename)

    def create_import(
        self, session: Session, submission: IntakeSubmission, parsed: object, actor_email: str | None
    ) -> cm.CanadaLegacyImportRun:
        if not isinstance(parsed, CanadaCase) or submission.case_id is None:
            raise DomainValidationError("validated Canada intake is incomplete")
        return CanadaLegacyImportService(session).preview_case(
            submission.case_id,
            parsed,
            source_type="google_verified_csv",
            source_identifier=submission.source_filename or "google-forms.csv",
            source_hash=submission.source_hash,
            imported_by=actor_email,
        )


ADAPTERS: dict[str, IntakeSourceAdapter] = {
    GOOGLE_FORMS_CSV: GoogleFormsCsvIntakeAdapter(),
}


class IntakeService:
    """Durable orchestration in front of the existing M11 import boundary."""

    def __init__(self, session: Session, storage: StorageProvider):
        self.session = session
        self.storage = storage

    def receive_and_process(
        self,
        *,
        source_type: str,
        content: bytes,
        filename: str | None,
        source_external_id: str | None = None,
        requested_case_id: uuid.UUID | None = None,
        actor=None,
    ) -> IntakeSubmission:
        adapter = self._adapter(source_type)
        if not content:
            raise DomainValidationError("intake source is empty")
        if len(content) > adapter.max_bytes:
            raise DomainValidationError("intake source exceeds the configured size limit")
        digest = hashlib.sha256(content).hexdigest()
        external_id = source_external_id.strip()[:255] if source_external_id and source_external_id.strip() else None
        existing = self._duplicate(source_type, digest, external_id, MAPPING_VERSION)
        if existing is not None:
            existing.duplicate_receive_count += 1
            record_audit(
                self.session, actor=actor, action="INTAKE_DUPLICATE_IGNORED",
                target_entity_type="INTAKE_SUBMISSION", target_entity_id=existing.id,
                case_id=existing.case_id,
                metadata={"source_type": source_type, "mapping_version": MAPPING_VERSION},
            )
            self.session.commit()
            return self._decorate(existing)

        stored = self.storage.save(io.BytesIO(content), max_bytes=adapter.max_bytes)
        submission = IntakeSubmission(
            source_type=source_type,
            source_external_id=external_id,
            source_filename=PurePath(filename or "google-forms.csv").name[:255],
            source_hash=digest,
            source_size_bytes=stored.size_bytes,
            raw_source_reference=stored.key,
            mapping_version=MAPPING_VERSION,
            requested_case_id=requested_case_id,
        )
        self.session.add(submission)
        try:
            self.session.flush()
            record_audit(
                self.session, actor=actor, action="INTAKE_RECEIVED",
                target_entity_type="INTAKE_SUBMISSION", target_entity_id=submission.id,
                metadata={"source_type": source_type, "mapping_version": MAPPING_VERSION},
            )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            self.storage.delete(stored.key)
            existing = self._duplicate(source_type, digest, external_id, MAPPING_VERSION)
            if existing is None:
                raise
            existing.duplicate_receive_count += 1
            record_audit(
                self.session, actor=actor, action="INTAKE_DUPLICATE_IGNORED",
                target_entity_type="INTAKE_SUBMISSION", target_entity_id=existing.id,
                case_id=existing.case_id,
                metadata={"source_type": source_type, "mapping_version": MAPPING_VERSION},
            )
            self.session.commit()
            return self._decorate(existing)
        return self.process(submission.id, actor=actor)

    def process(self, submission_id: uuid.UUID, *, actor=None) -> IntakeSubmission:
        submission = self.get(submission_id, decorate=False)
        if submission.processing_status in {"PROCESSED", "NEEDS_REVIEW"}:
            return self._decorate(submission)
        adapter = self._adapter(submission.source_type)
        attempt_number = int(self.session.scalar(
            select(func.count(IntakeProcessingAttempt.id)).where(
                IntakeProcessingAttempt.submission_id == submission.id
            )
        ) or 0) + 1
        now = datetime.now(timezone.utc)
        attempt = IntakeProcessingAttempt(
            submission_id=submission.id,
            attempt_number=attempt_number,
            mapping_version=MAPPING_VERSION,
            status="PROCESSING",
            started_at=now,
        )
        submission.processing_status = "PROCESSING"
        submission.processing_started_at = now
        submission.processing_completed_at = None
        submission.failure_code = None
        submission.failure_message = None
        self.session.add(attempt)
        self.session.commit()

        phase = "source_validation"
        try:
            with self.storage.open(submission.raw_source_reference) as source:
                content = source.read(adapter.max_bytes + 1)
            if len(content) > adapter.max_bytes:
                raise DomainValidationError("stored source exceeds the configured size limit")
            parsed = adapter.parse_source(content, submission.source_filename or "google-forms.csv")
            normalized = adapter.normalize(parsed)
            adapter.validate_source(normalized)
            phase = "case_resolution"
            case, created_case, matched_case = self._resolve_case(submission, actor=actor)
            submission.case_id = case.id
            attempt.case_id = case.id
            attempt.created_case = int(created_case)
            attempt.matched_existing_case = int(matched_case)
            self.session.commit()

            phase = "import_mapping"
            run = adapter.create_import(
                self.session, submission, normalized, getattr(actor, "email", None)
            )
            submission.import_run_id = run.id
            phase = "import_apply"
            processed_run = CanadaLegacyImportService(self.session).apply(
                run.id, mode="safe", reviewed_by=getattr(actor, "email", None)
            )
            changes = CanadaLegacyImportService(self.session).changes(processed_run.id)
            issue_count = sum(
                item.status in {"new", "conflict", "ambiguous", "accepted"}
                for item in changes
            )
            completed = datetime.now(timezone.utc)
            status = "NEEDS_REVIEW" if issue_count else "PROCESSED"
            submission.processing_status = status
            submission.processing_completed_at = completed
            submission.issue_count = issue_count
            submission.failure_code = None
            submission.failure_message = None
            attempt.status = status
            attempt.completed_at = completed
            attempt.case_id = case.id
            attempt.import_run_id = processed_run.id
            attempt.created_case = int(created_case)
            attempt.matched_existing_case = int(matched_case)
            attempt.issue_count = issue_count
            record_audit(
                self.session, actor=actor,
                action="INTAKE_REVIEW_REQUIRED" if issue_count else "INTAKE_PROCESSED",
                target_entity_type="INTAKE_SUBMISSION", target_entity_id=submission.id,
                case_id=case.id,
                metadata={
                    "source_type": submission.source_type,
                    "mapping_version": MAPPING_VERSION,
                    "created_case": created_case,
                    "matched_existing_case": matched_case,
                    "issue_count": issue_count,
                },
            )
            self.session.commit()
            LOGGER.info(
                "intake_processed",
                extra={
                    "intake_submission_id": str(submission.id),
                    "case_id": str(case.id),
                    "status": status,
                    "issue_count": issue_count,
                },
            )
        except AmbiguousCaseMatch:
            self._complete_failure(
                submission, attempt, actor=actor, status="NEEDS_REVIEW",
                code="AMBIGUOUS_CASE_MATCH",
                message="Multiple existing applications are linked to this source. Select the correct application and retry.",
            )
        except (DomainValidationError, DomainNotFound, ValueError, UnicodeError) as error:
            LOGGER.info(
                "intake_processing_rejected",
                extra={
                    "intake_submission_id": str(submission.id),
                    "error_type": type(error).__name__,
                    "processing_phase": phase,
                },
            )
            if phase == "source_validation":
                code = "SOURCE_VALIDATION_FAILED"
                message = "The source could not be parsed or validated. Correct the source and retry."
            elif phase == "import_apply":
                code = "IMPORT_APPLY_FAILED"
                message = "The validated source could not be applied. Review the intake and retry."
            else:
                code = "INTAKE_PROCESSING_FAILED"
                message = "The validated source could not be processed. Review the intake and retry."
            self._complete_failure(
                submission, attempt, actor=actor, status="FAILED",
                code=code, message=message,
            )
        except StorageObjectNotFound:
            self._complete_failure(
                submission, attempt, actor=actor, status="FAILED",
                code="RAW_SOURCE_UNAVAILABLE",
                message="The stored source is unavailable. Restore it before retrying.",
            )
        except Exception as error:
            self.session.rollback()
            LOGGER.exception(
                "intake_processing_failed",
                extra={"intake_submission_id": str(submission.id)},
            )
            submission = self.get(submission_id, decorate=False)
            attempt = self.session.get(IntakeProcessingAttempt, attempt.id) or attempt
            self._complete_failure(
                submission, attempt, actor=actor, status="FAILED",
                code="IMPORT_APPLY_FAILED" if phase == "import_apply" else "INTAKE_PROCESSING_FAILED",
                message=(
                    "The validated source could not be applied. Review the intake and retry."
                    if phase == "import_apply"
                    else "The intake could not be processed. Retry after checking the system status."
                ),
            )
        return self._decorate(submission)

    def retry(
        self, submission_id: uuid.UUID, *, requested_case_id: uuid.UUID | None = None, actor=None
    ) -> IntakeSubmission:
        submission = self.get(submission_id, decorate=False)
        if submission.processing_status not in {"FAILED", "NEEDS_REVIEW"}:
            raise DomainValidationError("only failed or review-required intake can be retried")
        if requested_case_id is not None:
            submission.requested_case_id = requested_case_id
        submission.retry_count += 1
        submission.processing_status = "RECEIVED"
        self.session.commit()
        return self.process(submission.id, actor=actor)

    def list(self) -> list[IntakeSubmission]:
        priority = {
            "FAILED": 0, "NEEDS_REVIEW": 1, "PROCESSING": 2,
            "RECEIVED": 3, "PROCESSED": 4,
        }
        rows = list(self.session.scalars(
            select(IntakeSubmission).order_by(IntakeSubmission.received_at.desc())
        ))
        rows.sort(key=lambda row: (priority[row.processing_status], -row.received_at.timestamp()))
        return [self._decorate(row) for row in rows]

    def get(self, submission_id: uuid.UUID, *, decorate: bool = True) -> IntakeSubmission:
        row = self.session.get(IntakeSubmission, submission_id)
        if row is None:
            raise DomainNotFound("Intake submission not found")
        return self._decorate(row) if decorate else row

    def attempts(self, submission_id: uuid.UUID) -> list[IntakeProcessingAttempt]:
        self.get(submission_id, decorate=False)
        return list(self.session.scalars(
            select(IntakeProcessingAttempt)
            .where(IntakeProcessingAttempt.submission_id == submission_id)
            .order_by(IntakeProcessingAttempt.attempt_number.desc())
        ))

    def metrics(self) -> dict[str, int]:
        status_counts = dict(self.session.execute(
            select(IntakeSubmission.processing_status, func.count(IntakeSubmission.id))
            .group_by(IntakeSubmission.processing_status)
        ).all())
        resolutions = self.session.execute(
            select(
                IntakeProcessingAttempt.submission_id,
                func.max(IntakeProcessingAttempt.created_case),
                func.max(IntakeProcessingAttempt.matched_existing_case),
            ).group_by(IntakeProcessingAttempt.submission_id)
        ).all()
        created = sum(bool(created_case) for _submission_id, created_case, _matched in resolutions)
        matched = sum(
            bool(matched_case) and not bool(created_case)
            for _submission_id, created_case, matched_case in resolutions
        )
        return {
            "submissions_received": int(self.session.scalar(select(func.count(IntakeSubmission.id))) or 0),
            "successfully_processed": int(status_counts.get("PROCESSED", 0)),
            "duplicates_ignored": int(self.session.scalar(select(func.coalesce(func.sum(IntakeSubmission.duplicate_receive_count), 0))) or 0),
            "new_cases_created": int(created),
            "existing_cases_matched": int(matched),
            "review_required": int(status_counts.get("NEEDS_REVIEW", 0)),
            "failed": int(status_counts.get("FAILED", 0)),
        }

    def _resolve_case(self, submission: IntakeSubmission, *, actor=None):
        if submission.case_id is not None:
            case = self.session.get(models.Case, submission.case_id)
            if case is None:
                raise DomainNotFound("linked application no longer exists")
            # A retry reuses its prior resolution; it is neither a newly
            # created nor a newly matched application for metrics purposes.
            return case, False, False

        if submission.requested_case_id is not None:
            case = self.session.get(models.Case, submission.requested_case_id)
            if case is None:
                raise DomainNotFound("selected application was not found")
            return case, False, True

        candidate_ids: set[uuid.UUID] = set()
        if submission.source_external_id:
            candidate_ids.update(self.session.scalars(
                select(IntakeSubmission.case_id).where(
                    IntakeSubmission.id != submission.id,
                    IntakeSubmission.source_type == submission.source_type,
                    IntakeSubmission.source_external_id == submission.source_external_id,
                    IntakeSubmission.case_id.is_not(None),
                )
            ))
        if len(candidate_ids) > 1:
            raise AmbiguousCaseMatch("multiple deterministic case links exist")
        if candidate_ids:
            case = self.session.get(models.Case, next(iter(candidate_ids)))
            if case is None:
                raise DomainNotFound("linked application was not found")
            return case, False, True
        case = CaseApplicationService(self.session).create_case(CaseCreate(), audit_actor=actor)
        return case, True, False

    def _complete_failure(
        self, submission: IntakeSubmission, attempt: IntakeProcessingAttempt, *, actor,
        status: str, code: str, message: str,
    ) -> None:
        completed = datetime.now(timezone.utc)
        submission.processing_status = status
        submission.processing_completed_at = completed
        submission.failure_code = code
        submission.failure_message = message
        submission.issue_count = 1
        attempt.status = status
        attempt.completed_at = completed
        attempt.failure_code = code
        attempt.failure_message = message
        attempt.case_id = submission.case_id
        record_audit(
            self.session, actor=actor,
            action="INTAKE_REVIEW_REQUIRED" if status == "NEEDS_REVIEW" else "INTAKE_FAILED",
            target_entity_type="INTAKE_SUBMISSION", target_entity_id=submission.id,
            case_id=submission.case_id,
            outcome="FAILURE" if status == "FAILED" else "REVIEW_REQUIRED",
            metadata={"source_type": submission.source_type, "failure_code": code},
        )
        self.session.commit()

    def _duplicate(
        self, source_type: str, digest: str, external_id: str | None, mapping_version: str
    ) -> IntakeSubmission | None:
        identities = [IntakeSubmission.source_hash == digest]
        if external_id:
            identities.append(IntakeSubmission.source_external_id == external_id)
        return self.session.scalar(select(IntakeSubmission).where(
            IntakeSubmission.source_type == source_type,
            IntakeSubmission.mapping_version == mapping_version,
            or_(*identities),
        ).order_by(IntakeSubmission.received_at))

    @staticmethod
    def _adapter(source_type: str) -> IntakeSourceAdapter:
        try:
            return ADAPTERS[source_type]
        except KeyError as error:
            raise DomainValidationError("unsupported intake source type") from error

    def _decorate(self, submission: IntakeSubmission) -> IntakeSubmission:
        display_name = None
        case_number = None
        if submission.case_id:
            case = self.session.get(models.Case, submission.case_id)
            case_number = case.case_number if case else None
            applicants = [person for person in self.session.scalars(
                select(models.Person).where(models.Person.case_id == submission.case_id)
                .order_by(models.Person.created_at)
            ) if "applicant" in person.roles]
            display_name = (
                f"{applicants[0].first_name} {applicants[0].last_name}".strip()
                if applicants else UNIDENTIFIED_APPLICANT
            )
        setattr(submission, "applicant_display_name", display_name)
        setattr(submission, "case_number", case_number)
        return submission
