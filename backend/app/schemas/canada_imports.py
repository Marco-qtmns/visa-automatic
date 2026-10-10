from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ImportReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CanadaImportRunRead(ImportReadModel):
    id: uuid.UUID
    case_id: uuid.UUID
    source_type: str
    source_identifier: str
    source_hash: str
    mapping_version: str
    status: str
    imported_by: str | None
    counts_json: dict[str, int]
    warnings_json: list[str]
    error_summary: str | None
    created_at: datetime
    completed_at: datetime | None


class CanadaImportCandidateRead(ImportReadModel):
    id: uuid.UUID
    import_run_id: uuid.UUID
    domain_section: str
    employee_label: str
    target_label: str
    classification: str
    target_entity_type: str
    target_entity_id: uuid.UUID | None
    target_field: str
    operation: str
    source_path: str
    source_record_key: str
    source_classification: str
    source_reference: str
    raw_value_json: Any
    proposed_value_json: Any
    current_value_json: Any | None
    status: str
    conflict_type: str | None
    review_policy: str
    conflict_policy: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    canonical_review_state: str | None = None
    created_at: datetime


class CanadaImportDetail(BaseModel):
    run: CanadaImportRunRead
    changes: list[CanadaImportCandidateRead]


class ImportApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["accepted", "safe"] = "accepted"
    reviewed_by: str | None = Field(default=None, max_length=255)


class ImportReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewed_by: str | None = Field(default=None, max_length=255)


class ImportResolveRequest(ImportReviewRequest):
    decision: Literal["keep_current", "use_imported"]
    host_type: Literal["person", "organization"] | None = None


class ImportConfirmRequest(ImportReviewRequest):
    value: Any
    host_type: Literal["person", "organization"] | None = None


class ImportMappingRead(BaseModel):
    mapping_version: str
    count: int
    mappings: list[dict[str, str]]
