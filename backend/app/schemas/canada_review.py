from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReviewReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CanadaTrvReviewApplicationRead(ReviewReadModel):
    id: uuid.UUID
    import_id: uuid.UUID
    case_id: uuid.UUID
    import_row_number: int
    status: str
    confirmed_by: str | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CanadaTrvReviewRevisionRead(ReviewReadModel):
    id: uuid.UUID
    old_value_json: Any
    new_value_json: Any
    actor_id: str
    created_at: datetime


class CanadaTrvReviewFieldRead(ReviewReadModel):
    id: uuid.UUID
    field_id: str
    section_id: str
    target_path: str
    source_csv_column_1based: int | None
    source_header: str
    raw_value: str
    normalized_value_json: Any
    edited_value_json: Any | None
    applicability: str
    review_status: str
    evidence: str | None
    requirement_mode: str
    reviewer_id: str | None
    reviewed_at: datetime | None
    label_pt: str
    normalized_type: str
    ui: dict[str, Any]
    revisions: list[CanadaTrvReviewRevisionRead]


class CanadaTrvReviewDetail(BaseModel):
    application: CanadaTrvReviewApplicationRead
    schema_id: str
    schema_version: str
    variant_id: str
    source_filename: str
    sections: list[dict[str, Any]]
    fields: list[CanadaTrvReviewFieldRead]
    normalized_data: dict[str, Any]
    validation_issues: list[dict[str, Any]]
    section_reviews: dict[str, Any]


class ReviewFieldUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Any


class ReviewSectionConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_id: str = Field(min_length=1, max_length=64)
