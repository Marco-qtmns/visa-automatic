from __future__ import annotations

import os
import uuid
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..schemas import core as schemas
from ..storage import StorageLimitExceeded, StorageProvider
from .core import CoreDataService, DomainNotFound, DomainValidationError
from .requirements import DEFAULT_RULE_CATALOG


SUPPORTED_MIME_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png"})


class UnsupportedDocumentFile(DomainValidationError):
    pass


class DocumentUploadTooLarge(DomainValidationError):
    pass


def configured_max_upload_bytes() -> int:
    raw_value = os.environ.get("MAX_UPLOAD_SIZE_MB", "20")
    try:
        megabytes = int(raw_value)
    except ValueError as error:
        raise DomainValidationError("MAX_UPLOAD_SIZE_MB must be a positive integer") from error
    if megabytes <= 0:
        raise DomainValidationError("MAX_UPLOAD_SIZE_MB must be a positive integer")
    return megabytes * 1024 * 1024


def detect_mime_type(header: bytes) -> str | None:
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


def safe_original_filename(filename: str | None) -> str:
    normalized = (filename or "document").replace("\\", "/").split("/")[-1].strip()
    if not normalized or any(ord(character) < 32 for character in normalized):
        return "document"
    return normalized[:512]


def validate_document_type(document_type: str | None) -> None:
    if document_type is not None and document_type not in DEFAULT_RULE_CATALOG.document_types:
        raise DomainValidationError(f"unknown document type: {document_type}")


class DocumentUploadService:
    def __init__(self, session: Session, storage: StorageProvider):
        self.session = session
        self.storage = storage
        self.core = CoreDataService(session)

    def upload(
        self,
        case_id: uuid.UUID,
        source: BinaryIO,
        *,
        original_filename: str | None,
        declared_mime_type: str | None,
        document_type: str | None = None,
        person_id: uuid.UUID | None = None,
    ) -> models.Document:
        self.core.get_case(case_id)
        validate_document_type(document_type)
        self.core._belongs_to_case(models.Person, person_id, case_id, "person")

        header = source.read(16)
        source.seek(0)
        detected_mime_type = detect_mime_type(header)
        if (
            declared_mime_type not in SUPPORTED_MIME_TYPES
            or detected_mime_type is None
            or detected_mime_type != declared_mime_type
        ):
            raise UnsupportedDocumentFile("PDF, JPEG or PNG files are supported")

        try:
            stored = self.storage.save(source, max_bytes=configured_max_upload_bytes())
        except StorageLimitExceeded as error:
            raise DocumentUploadTooLarge("file exceeds the maximum upload size") from error

        try:
            return self.core.create_document(
                case_id,
                schemas.DocumentCreate(
                    person_id=person_id,
                    document_type=document_type,
                    original_filename=safe_original_filename(original_filename),
                    storage_path=stored.key,
                    mime_type=detected_mime_type,
                    source_type="manual_upload",
                    classification_status="unclassified",
                    quality_status="not_checked",
                    metadata_json={"size_bytes": stored.size_bytes},
                ),
            )
        except Exception:
            self.storage.delete(stored.key)
            raise


class DocumentMatchingService:
    """Owns deterministic metadata compatibility and manual match persistence."""

    def __init__(self, session: Session):
        self.session = session
        self.core = CoreDataService(session)

    def _compatible(
        self,
        requirement: models.Requirement,
        document: models.Document,
        *,
        document_type: str | None = None,
        person_id: uuid.UUID | None = None,
        use_overrides: bool = False,
    ) -> tuple[bool, str]:
        effective_type = document_type if use_overrides else document.document_type
        effective_person_id = person_id if use_overrides else document.person_id
        if requirement.case_id != document.case_id:
            return False, "requirement and document belong to different cases"
        if effective_type is None:
            return False, "document type must be assigned before matching"
        if effective_type != requirement.document_type:
            return False, "document type does not match requirement"
        if effective_person_id is None:
            return False, "document owner must be assigned before matching"
        if requirement.owner_person_id is not None:
            if effective_person_id != requirement.owner_person_id:
                return False, "document owner does not match requirement owner"
            return True, ""
        person = self.session.get(models.Person, effective_person_id)
        if person is None or person.case_id != document.case_id:
            return False, "document owner is not part of the case"
        if requirement.owner_role not in person.roles:
            return False, "document owner does not hold the required role"
        return True, ""

    def compatible_requirements(self, document_id: uuid.UUID) -> list[models.Requirement]:
        document = self.core.get_document(document_id)
        requirements = self.session.scalars(
            select(models.Requirement)
            .where(
                models.Requirement.case_id == document.case_id,
                models.Requirement.active.is_(True),
            )
            .order_by(models.Requirement.created_at, models.Requirement.id)
        )
        return [item for item in requirements if self._compatible(item, document)[0]]

    def create_match(
        self,
        requirement_id: uuid.UUID,
        document_id: uuid.UUID,
        payload: schemas.RequirementDocumentMatchCreate,
    ) -> models.RequirementDocumentMatch:
        requirement = self.core.get_requirement(requirement_id)
        document = self.core.get_document(document_id)
        if not requirement.active:
            raise DomainValidationError("inactive requirement cannot receive a new match")
        existing = self.session.scalar(
            select(models.RequirementDocumentMatch).where(
                models.RequirementDocumentMatch.requirement_id == requirement_id,
                models.RequirementDocumentMatch.document_id == document_id,
            )
        )
        if existing is not None:
            raise DomainValidationError("document is already matched to requirement")
        compatible, reason = self._compatible(requirement, document)
        if not compatible:
            raise DomainValidationError(reason)
        match = models.RequirementDocumentMatch(
            requirement_id=requirement_id,
            document_id=document_id,
            **payload.model_dump(),
        )
        self.session.add(match)
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise DomainValidationError("document is already matched to requirement") from error
        self.session.refresh(match)
        from .quality import RequirementCompletenessService

        RequirementCompletenessService(self.session).evaluate(
            requirement_id, trigger="match_added"
        )
        return match

    def remove_match(self, requirement_id: uuid.UUID, document_id: uuid.UUID) -> None:
        match = self.session.scalar(
            select(models.RequirementDocumentMatch).where(
                models.RequirementDocumentMatch.requirement_id == requirement_id,
                models.RequirementDocumentMatch.document_id == document_id,
            )
        )
        if match is None:
            raise DomainNotFound("RequirementDocumentMatch not found")
        self.session.delete(match)
        self.session.commit()
        from .quality import RequirementCompletenessService

        RequirementCompletenessService(self.session).evaluate(
            requirement_id, trigger="match_removed"
        )

    def update_document(
        self,
        document_id: uuid.UUID,
        payload: schemas.DocumentUpdate,
        *,
        commit: bool = True,
    ) -> models.Document:
        document = self.core.get_document(document_id)
        validate_document_type(payload.document_type if "document_type" in payload.model_fields_set else document.document_type)
        if "person_id" in payload.model_fields_set:
            self.core._belongs_to_case(models.Person, payload.person_id, document.case_id, "person")
        prospective_type = (
            payload.document_type
            if "document_type" in payload.model_fields_set
            else document.document_type
        )
        prospective_person = (
            payload.person_id if "person_id" in payload.model_fields_set else document.person_id
        )
        matches = self.session.scalars(
            select(models.RequirementDocumentMatch).where(
                models.RequirementDocumentMatch.document_id == document.id
            )
        )
        for match in matches:
            requirement = self.core.get_requirement(match.requirement_id)
            compatible, reason = self._compatible(
                requirement,
                document,
                document_type=prospective_type,
                person_id=prospective_person,
                use_overrides=True,
            )
            if not compatible:
                raise DomainValidationError(
                    f"remove incompatible document matches before changing metadata: {reason}"
                )
        if commit:
            updated = self.core.update_document(document_id, payload)
            from .quality import RequirementCompletenessService

            RequirementCompletenessService(self.session).evaluate_for_document(
                document_id, trigger="document_metadata_update"
            )
            return updated
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(document, key, value)
        self.session.add(document)
        self.session.flush()
        return document

    def list_document_matches(
        self, document_id: uuid.UUID
    ) -> list[models.RequirementDocumentMatch]:
        self.core.get_document(document_id)
        return list(self.session.scalars(
            select(models.RequirementDocumentMatch)
            .where(models.RequirementDocumentMatch.document_id == document_id)
            .order_by(models.RequirementDocumentMatch.created_at, models.RequirementDocumentMatch.id)
        ))

    def list_requirement_matches(
        self, requirement_id: uuid.UUID
    ) -> list[models.RequirementDocumentMatch]:
        self.core.get_requirement(requirement_id)
        return list(self.session.scalars(
            select(models.RequirementDocumentMatch)
            .where(models.RequirementDocumentMatch.requirement_id == requirement_id)
            .order_by(models.RequirementDocumentMatch.created_at, models.RequirementDocumentMatch.id)
        ))

    def list_case_matches(self, case_id: uuid.UUID) -> list[models.RequirementDocumentMatch]:
        self.core.get_case(case_id)
        return list(self.session.scalars(
            select(models.RequirementDocumentMatch)
            .join(models.Requirement)
            .where(models.Requirement.case_id == case_id)
            .order_by(models.RequirementDocumentMatch.created_at, models.RequirementDocumentMatch.id)
        ))
