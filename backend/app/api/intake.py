from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from ..authorization import CurrentUser
from ..database import get_session
from ..schemas import intake as schemas
from ..services.core import DomainValidationError
from ..services.intake import GOOGLE_FORMS_CSV, IntakeService
from ..storage import LocalStorageProvider, StorageProvider


router = APIRouter(tags=["Automated intake"])
SessionDep = Annotated[Session, Depends(get_session)]


def intake_storage_provider() -> StorageProvider:
    default_root = Path(__file__).resolve().parents[2] / "intake-storage"
    return LocalStorageProvider(Path(os.environ.get("INTAKE_STORAGE_ROOT", str(default_root))))


IntakeStorageDep = Annotated[StorageProvider, Depends(intake_storage_provider)]


@router.post(
    "/intake/submissions/google-forms-csv",
    response_model=schemas.IntakeSubmissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def receive_google_forms_csv(
    session: SessionDep,
    storage: IntakeStorageDep,
    user: CurrentUser,
    file: UploadFile = File(...),
    source_external_id: str | None = Form(default=None),
    case_id: uuid.UUID | None = Form(default=None),
):
    try:
        content = await file.read(5 * 1024 * 1024 + 1)
        return IntakeService(session, storage).receive_and_process(
            source_type=GOOGLE_FORMS_CSV,
            content=content,
            filename=file.filename,
            source_external_id=source_external_id,
            requested_case_id=case_id,
            actor=user,
        )
    finally:
        await file.close()


@router.get("/intake/submissions", response_model=list[schemas.IntakeSubmissionRead])
def list_intake_submissions(session: SessionDep, storage: IntakeStorageDep):
    return IntakeService(session, storage).list()


@router.get("/intake/submissions/{submission_id}", response_model=schemas.IntakeDetailRead)
def get_intake_submission(submission_id: uuid.UUID, session: SessionDep, storage: IntakeStorageDep):
    service = IntakeService(session, storage)
    return {"submission": service.get(submission_id), "attempts": service.attempts(submission_id)}


@router.post(
    "/intake/submissions/{submission_id}/retry",
    response_model=schemas.IntakeSubmissionRead,
)
def retry_intake_submission(
    submission_id: uuid.UUID,
    payload: schemas.IntakeRetryRequest,
    session: SessionDep,
    storage: IntakeStorageDep,
    user: CurrentUser,
):
    return IntakeService(session, storage).retry(
        submission_id, requested_case_id=payload.case_id, actor=user
    )


@router.get("/intake/metrics", response_model=schemas.IntakeMetricsRead)
def intake_metrics(session: SessionDep, storage: IntakeStorageDep):
    return IntakeService(session, storage).metrics()
