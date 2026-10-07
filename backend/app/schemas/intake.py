from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


IntakeStatus = Literal["RECEIVED", "PROCESSING", "PROCESSED", "NEEDS_REVIEW", "FAILED"]


class IntakeReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class IntakeSubmissionRead(IntakeReadModel):
    id: uuid.UUID
    source_type: str
    source_external_id: str | None
    source_filename: str | None
    received_at: datetime
    mapping_version: str
    processing_status: IntakeStatus
    case_id: uuid.UUID | None
    import_run_id: uuid.UUID | None
    processing_started_at: datetime | None
    processing_completed_at: datetime | None
    failure_code: str | None
    failure_message: str | None
    issue_count: int
    duplicate_receive_count: int
    retry_count: int
    applicant_display_name: str | None = None
    case_number: str | None = None


class IntakeAttemptRead(IntakeReadModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    attempt_number: int
    mapping_version: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    failure_code: str | None
    failure_message: str | None
    case_id: uuid.UUID | None
    import_run_id: uuid.UUID | None
    created_case: int
    matched_existing_case: int
    issue_count: int


class IntakeDetailRead(BaseModel):
    submission: IntakeSubmissionRead
    attempts: list[IntakeAttemptRead]


class IntakeRetryRequest(BaseModel):
    case_id: uuid.UUID | None = None


class IntakeMetricsRead(BaseModel):
    submissions_received: int
    successfully_processed: int
    duplicates_ignored: int
    new_cases_created: int
    existing_cases_matched: int
    review_required: int
    failed: int
