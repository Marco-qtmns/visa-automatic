from __future__ import annotations

import uuid
from pathlib import PurePath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from ..authorization import CurrentUser
from ..database import get_session
from ..schemas import canada_review as schemas
from ..services.canada_trv_review import CanadaTrvReviewService
from ..services.canada_trv_schema import CsvSchemaMismatch, SchemaRegistry
from ..services.core import DomainValidationError
from .intake import IntakeStorageDep


router = APIRouter(tags=["Canada TRV schema review"])
SessionDep = Annotated[Session, Depends(get_session)]


def _detail(service: CanadaTrvReviewService, application_id: uuid.UUID) -> dict[str, Any]:
    application = service.get(application_id)
    definitions = {item["field_id"]: item for item in service.registry.fields}
    fields = []
    for field in application.fields:
        definition = definitions[field.field_id]
        fields.append({
            "id": field.id, "field_id": field.field_id, "section_id": field.section_id,
            "target_path": field.target_path, "source_csv_column_1based": field.source_csv_column_1based,
            "source_header": field.source_header, "raw_value": field.raw_value,
            "normalized_value_json": field.normalized_value_json, "edited_value_json": field.edited_value_json,
            "applicability": field.applicability, "review_status": field.review_status,
            "evidence": field.evidence, "requirement_mode": field.requirement_mode,
            "reviewer_id": field.reviewer_id, "reviewed_at": field.reviewed_at,
            "label_pt": definition["label_pt"], "normalized_type": definition["normalized_type"],
            "ui": definition["ui"], "revisions": field.revisions,
        })
    batch = application.import_batch
    return {
        "application": application,
        "schema_id": batch.schema_id, "schema_version": batch.schema_version,
        "variant_id": batch.variant_id, "source_filename": batch.source_filename,
        "sections": list(service.registry.sections), "fields": fields,
        "normalized_data": application.normalized_data_json,
        "validation_issues": application.validation_issues_json,
        "section_reviews": application.section_reviews_json,
    }


@router.get("/canada-trv-review-schema")
def review_schema():
    return SchemaRegistry().public_schema()


@router.post(
    "/canada-trv-reviews/import",
    response_model=list[schemas.CanadaTrvReviewApplicationRead],
    status_code=status.HTTP_201_CREATED,
)
async def import_review_csv(
    session: SessionDep,
    storage: IntakeStorageDep,
    user: CurrentUser,
    file: UploadFile = File(...),
    case_id: uuid.UUID | None = Form(default=None),
):
    content = await file.read(5 * 1024 * 1024 + 1)
    try:
        if not content:
            raise DomainValidationError("CSV is empty")
        if len(content) > 5 * 1024 * 1024:
            raise DomainValidationError("CSV exceeds the configured 5 MB limit")
        stored = storage.save_bytes(content) if hasattr(storage, "save_bytes") else None
        if stored is None:
            import io
            stored = storage.save(io.BytesIO(content), max_bytes=5 * 1024 * 1024)
        try:
            return CanadaTrvReviewService(session).import_csv(
                content, PurePath(file.filename or "google-forms.csv").name,
                stored.key, requested_case_id=case_id, actor=user,
            )
        except CsvSchemaMismatch as error:
            domain_error = DomainValidationError(str(error))
            domain_error.api_detail = error.detail
            raise domain_error from error
        except Exception:
            storage.delete(stored.key)
            raise
    finally:
        await file.close()


@router.get("/cases/{case_id}/canada-trv-reviews", response_model=list[schemas.CanadaTrvReviewApplicationRead])
def list_case_reviews(case_id: uuid.UUID, session: SessionDep):
    return CanadaTrvReviewService(session).list_for_case(case_id)


@router.get("/canada-trv-reviews/{application_id}", response_model=schemas.CanadaTrvReviewDetail)
def get_review(application_id: uuid.UUID, session: SessionDep):
    service = CanadaTrvReviewService(session)
    return _detail(service, application_id)


@router.patch("/canada-trv-review-fields/{field_id}", response_model=schemas.CanadaTrvReviewFieldRead)
def update_review_field(field_id: uuid.UUID, payload: schemas.ReviewFieldUpdate, session: SessionDep, user: CurrentUser):
    service = CanadaTrvReviewService(session)
    service.update_field(field_id, payload.value, actor=user)
    application_id = service._field(field_id).application_id
    detail = _detail(service, application_id)
    return next(item for item in detail["fields"] if item["id"] == field_id)


@router.post("/canada-trv-review-fields/{field_id}/confirm", response_model=schemas.CanadaTrvReviewFieldRead)
def confirm_review_field(field_id: uuid.UUID, session: SessionDep, user: CurrentUser):
    service = CanadaTrvReviewService(session)
    service.confirm_field(field_id, actor=user)
    application_id = service._field(field_id).application_id
    detail = _detail(service, application_id)
    return next(item for item in detail["fields"] if item["id"] == field_id)


@router.post("/canada-trv-reviews/{application_id}/confirm-section", response_model=schemas.CanadaTrvReviewDetail)
def confirm_review_section(application_id: uuid.UUID, payload: schemas.ReviewSectionConfirm, session: SessionDep, user: CurrentUser):
    service = CanadaTrvReviewService(session)
    service.confirm_section(application_id, payload.section_id, actor=user)
    return _detail(service, application_id)


@router.post("/canada-trv-reviews/{application_id}/confirm", response_model=schemas.CanadaTrvReviewDetail)
def confirm_review_application(application_id: uuid.UUID, session: SessionDep, user: CurrentUser):
    service = CanadaTrvReviewService(session)
    service.confirm_application(application_id, actor=user)
    return _detail(service, application_id)
