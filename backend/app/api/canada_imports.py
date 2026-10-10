from __future__ import annotations

import uuid
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from ..config.canada_import_mapping import MAPPING_SPEC_JSON, MAPPING_VERSION
from ..database import get_session
from ..schemas import canada_imports as schemas
from ..services.canada_imports import CanadaLegacyImportService, SOURCE_LIMITS
from ..services.core import DomainValidationError
from ..services.documents import DocumentUploadTooLarge


router = APIRouter(tags=["Canada legacy import"])
SessionDep = Annotated[Session, Depends(get_session)]


def service(session: Session) -> CanadaLegacyImportService:
    return CanadaLegacyImportService(session)


async def _preview(case_id: uuid.UUID, session: Session, file: UploadFile,
                   source_type: str, imported_by: str | None):
    if source_type not in SOURCE_LIMITS:
        raise DomainValidationError("unsupported Canada import source type")
    content = await file.read(SOURCE_LIMITS[source_type] + 1)
    if len(content) > SOURCE_LIMITS[source_type]:
        raise DocumentUploadTooLarge("Canada import source exceeds the configured size limit")
    return service(session).preview_upload(
        case_id, source_type, content,
        PurePath(file.filename or "import").name, imported_by,
    )


@router.get("/canada-import-mapping", response_model=schemas.ImportMappingRead)
def mapping_specification():
    return {"mapping_version": MAPPING_VERSION, "count": len(MAPPING_SPEC_JSON), "mappings": list(MAPPING_SPEC_JSON)}


@router.post("/cases/{case_id}/canada-imports/preview", response_model=schemas.CanadaImportRunRead, status_code=201)
async def preview_import(case_id: uuid.UUID, session: SessionDep, file: UploadFile = File(...),
                         source_type: str = Form(...), imported_by: str | None = Form(default=None)):
    return await _preview(case_id, session, file, source_type, imported_by)


@router.post("/cases/{case_id}/canada-imports", response_model=schemas.CanadaImportRunRead, status_code=201)
async def create_import(case_id: uuid.UUID, session: SessionDep, file: UploadFile = File(...),
                        source_type: str = Form(...), imported_by: str | None = Form(default=None)):
    return await _preview(case_id, session, file, source_type, imported_by)


@router.get("/cases/{case_id}/canada-imports", response_model=list[schemas.CanadaImportRunRead])
def list_imports(case_id: uuid.UUID, session: SessionDep):
    return service(session).list_runs(case_id)


@router.get("/canada-imports/{import_id}", response_model=schemas.CanadaImportDetail)
def get_import(import_id: uuid.UUID, session: SessionDep):
    importer = service(session)
    return {"run": importer.get_run(import_id), "changes": importer.changes(import_id)}


@router.get("/canada-imports/{import_id}/changes", response_model=list[schemas.CanadaImportCandidateRead])
def list_changes(import_id: uuid.UUID, session: SessionDep):
    return service(session).changes(import_id)


@router.post("/canada-imports/{import_id}/apply", response_model=schemas.CanadaImportRunRead)
def apply_import(import_id: uuid.UUID, payload: schemas.ImportApplyRequest, session: SessionDep):
    return service(session).apply(import_id, mode=payload.mode, reviewed_by=payload.reviewed_by)


@router.post("/canada-import-changes/{change_id}/accept", response_model=schemas.CanadaImportCandidateRead)
def accept_change(change_id: uuid.UUID, payload: schemas.ImportReviewRequest, session: SessionDep):
    return service(session).review(change_id, "accept", payload.reviewed_by)


@router.post("/canada-import-changes/{change_id}/reject", response_model=schemas.CanadaImportCandidateRead)
def reject_change(change_id: uuid.UUID, payload: schemas.ImportReviewRequest, session: SessionDep):
    return service(session).review(change_id, "reject", payload.reviewed_by)


@router.post("/canada-import-changes/{change_id}/resolve", response_model=schemas.CanadaImportCandidateRead)
def resolve_change(change_id: uuid.UUID, payload: schemas.ImportResolveRequest, session: SessionDep):
    return service(session).review(change_id, payload.decision, payload.reviewed_by, host_type=payload.host_type)


@router.post("/canada-import-changes/{change_id}/confirm", response_model=schemas.CanadaImportCandidateRead)
def confirm_change(change_id: uuid.UUID, payload: schemas.ImportConfirmRequest, session: SessionDep):
    return service(session).confirm(
        change_id, payload.value, payload.reviewed_by, host_type=payload.host_type
    )
